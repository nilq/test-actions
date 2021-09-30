#!python

"""
A tool for grabbing doc-strings from a Python project.
Producing a folder structure of MkDocs Markdown documents.

Author: Niels Horn (nh@valuer.ai)
"""

import sys
import os
import glob
import ruamel.yaml
import collections

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
from os.path import join, dirname
from ast import parse, NodeVisitor, get_docstring, Name, Call, Module, FunctionDef, ClassDef, Constant
from docstring_parser import parse as docstring_parse
from string import Template

USAGE = """
=====================================
Hello this is the documentation tool!
=====================================

Usage:
    doccer <source path> <markdown path>
"""

endpoint_decorators = [
    "get",
    "post",
    "put",
]

class_template = Template("""\
# `class` $name
$description
$method_table

---
""")

function_template = Template("""\
## `$name($params)`
$description

$table_of_params
""")

def param_table_from(params):
    if len(params) == 0:
        return ''

    table = "**Parameters:**\n\n| Name | Type | Description | Default |\n| --- | --- | --- | --- |\n"

    for p in params:
        table += f"| {p.arg_name} | {p.type_name} | {p.description} | {p.default or '*is required*'} |\n"

    return table

def function_to_markdown(name, doc):
    params = ', '.join([f'{n.arg_name}: {n.type_name}' for n in doc.params])
    return function_template.substitute(
        name=name,
        params=params,
        description=doc.short_description,
        table_of_params=param_table_from(doc.params)
    )

def decorator_names(node):
    def grab_id(n):
        if isinstance(name.func, Name):
            return name.func.id
        else:
            return name.func.attr

    names = []
    for name in node.decorator_list:
        if isinstance(name, Name):
            names.append(name.id)
        elif isinstance(name, Call):
            args = []
            n = grab_id(name)
            for arg in name.args:
                if isinstance(arg, Constant):
                    args.append(arg.value)

            names.append(n + ':' + ', '.join(args))

    return names


@dataclass
class ClassDoc(object):
    """A dataclass for containing class-meta.
    """
    def __init__(self, name, doc, decorators):
        self.name = name
        self.doc = doc
        self.methods = dict()
        self.decorators = decorators

    def append_method(self, name: str, doc):
        self.methods[name] = doc

    def __str__(self):
        """Generate markdown documentation from class meta-data.

        Returns
        -------
        str
            The markdown source generated on class template.
        """
        desc = self.doc.short_description
        desc = desc == "None" and ' ' or desc
        
        if len(self.methods) != 0:
            method_table = '\n**Methods:**\n\n| Name | Description | Returns |\n| --- | --- | --- |\n'
            
            for name, doc in self.methods.items():
                if name == '__init__':
                    continue

                returns = doc.returns is None and '`None`' or f'`{doc.returns.type_name}`'
                method_table += f'| `{name}` | {doc.short_description} | {returns} |\n'

        else:
            method_table = ''

        base = class_template.substitute(
            name=self.name,
            description=desc,
            method_table=method_table
        )

        for name, doc in self.methods.items():
            if doc.short_description != 'None':
                base += '\n' + function_to_markdown(name, doc)

        return base

@dataclass
class Doc(object):
    def __init__(self, name: str):
        self.name = name
        self.module: str = ""
        self.classes: List[ClassDoc] = list() 
        self.functions: Dict[str, dict] = dict()
        self.endpoints: Dict[str, str] = dict()

    def append_class(self, name, doc, decorators):
        new_class = ClassDoc(name, doc, decorators)

        self.classes.append(
            new_class
        )

        return new_class

    def append_function(self, name, doc, decorators):
        for decorator in decorators:
            for point in endpoint_decorators:
                if point in decorator:
                    self.endpoints[name] = decorator

        self.functions[name] = doc

    def compile(self):
        class_docs = []
        func_docs = []
        endpoint_docs = []

        for class_ in self.classes:
            class_docs.append(str(class_))

        for name, docs in self.functions.items():
            doc = function_to_markdown(name, docs)
                
            if name in self.endpoints.keys():
                endpoint_docs.append((name, doc, self.endpoints[name]))
            else:
                func_docs.append(doc)

        return class_docs, func_docs, endpoint_docs

class DocVisitor(NodeVisitor):
    def __init__(self, filename):
        self.doc = Doc(filename)

    def visit_Module(self, node: Module):
        self.doc.module = self.grab_doc(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: FunctionDef):
        self.doc.append_function(node.name, self.grab_doc(node), decorator_names(node))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ClassDef):
        new_class = self.doc.append_class(node.name, self.grab_doc(node), decorator_names(node))

        for content in node.body:
            if isinstance(content, FunctionDef):
                new_class.append_method(content.name, self.grab_doc(content))
                self.generic_visit(content)

        self.generic_visit(node)

    @staticmethod
    def grab_doc(node):
        """Grabs the documentation from given AST node.

        Parameters
        ----------
        node : Node
            The given Python AST node to check and grab doc-string from.

        Returns
        -------
        str
            The doc-string of the given AST node.

        """
        return docstring_parse(get_docstring(node).__str__())


def handle_docs(path, md_path):
    """Extracts all docstrings from a given Python source file.

    Parameters
    ----------
    path : str
        The path of given Python file.
    """
    with open(path, 'r', encoding='utf-8') as f:
        source = f.read()

    visitor = DocVisitor(path)
    visitor.visit(parse(source))

    table_of_contents = dict()

    def section(name, file):
        table_of_contents[name] = file

    md_file = Path(path).stem
    section(md_file, md_file + '.md')

    with open(join(md_path, md_file + '.md'), 'w+') as f:
        classes, funcs, endpoints = visitor.doc.compile()

        if endpoints != []:
            endpoint_dir = join(md_path, f'{md_file}_endpoints')
            os.makedirs(endpoint_dir, exist_ok=True)

            nav_endpoints = []

            for (name, doc, http) in endpoints:
                http_ = http.split(':')
                new_file = Path(http_[1]).stem + '.md'
                new_path = join(endpoint_dir, new_file)
                
                nav_endpoints.append({new_path[:-3].split('/')[-1]: join(f'{md_file}_endpoints', new_file) })
    
                with open(new_path, 'w+') as endpoint_f:
                    endpoint_f.write(f'# {http_[0].upper()} `{http_[1]}/` \n\n' + doc)

            section(f'{md_file} - Endpoints', nav_endpoints)

        f.write('---\n\n'.join(classes))
        f.write('---\n\n'.join(funcs))

    print(f'... Wrote docs to {md_file}')

    # print(visitor.doc.compile())

    return table_of_contents

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(USAGE)
        print("[error] Please provide relevant paths!")

        sys.exit(1)
    else:
        py_path = sys.argv[1]
        md_path = sys.argv[2]
        yml_path = sys.argv[3]

        table_of_contents = list()

        if os.path.isfile(py_path):
            print(f'Extracting docs from {py_path}!')
            for name, file in handle_docs(py_path, md_path).items():
                table_of_contents.append({name: file})

        else:
            for file in Path(py_path).rglob('*.py'):
                if file.stem == '__init__':
                    continue

                print(f'Extracting docs from {file}!')
                for name, file in handle_docs(file, md_path).items():
                    table_of_contents.append({name: file})

        yaml = ruamel.yaml.YAML()

        with open(yml_path, 'r') as f:
            data = yaml.load(f)

        data["nav"] = table_of_contents 

        with open(yml_path, 'w') as f:
            yaml.dump(data, f)
