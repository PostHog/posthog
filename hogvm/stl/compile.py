# Run from project root (cd ../..)
# python3 -m hogvm.stl.compile

import glob
import json

from posthog.hogql import ast
from posthog.hogql.bytecode import create_bytecode, parse_program

source = "hogvm/stl/src/*.hog"
target_ts = "hogvm/typescript/src/stl/bytecode.ts"
target_py = "hogvm/python/stl/bytecode.py"

bytecodes: dict[str, [list[str], list[any]]] = {}

for filename in glob.glob(source):
    with open(filename) as file:
        code = file.read()
    basename = filename.split("/")[-1].split(".")[0]
    program = parse_program(code)
    found = False
    for declaration in program.declarations:
        if isinstance(declaration, ast.Function) and declaration.name == basename:
            found = True
            bytecode = create_bytecode(declaration.body, args=declaration.params)
            bytecodes[basename] = [declaration.params, bytecode]
    if not found:
        print(f"Error: no function called {basename} was found in {filename}!")  # noqa: T201
        exit(1)

with open(target_ts, "w") as output:
    output.write("// This file is generated by hogvm/stl/compile.py\n")
    output.write("export const BYTECODE_STL: Record<string, [string[], any[]]> = {\n")
    for name, (params, bytecode) in bytecodes.items():
        output.write(f'  "{name}": [{json.dumps(params)}, {json.dumps(bytecode)}],\n')
    output.write("}\n")

with open(target_py, "w") as output:
    output.write("# This file is generated by hogvm/stl/compile.py\n")
    output.write("# fmt: off\n")
    output.write("BYTECODE_STL = {\n")
    for name, (params, bytecode) in bytecodes.items():
        output.write(f'  "{name}": [{json.dumps(params)}, {json.dumps(bytecode)}],\n')
    output.write("}\n")
    output.write("# fmt: on\n")
