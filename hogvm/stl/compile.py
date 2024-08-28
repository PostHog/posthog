# Run from project root:
# python3 -m hogvm.stl.compile

import glob
import json

from posthog.hogql import ast
from posthog.hogql.bytecode import create_bytecode, parse_program

source = "hogvm/stl/src/*.hog"
target = "hogvm/stl/dist/stl.json"

with open(target, "w") as output:
    for index, filename in enumerate(glob.glob(source)):
        with open(filename) as file:
            code = file.read()
        basename = filename.split("/")[-1].split(".")[0]
        program = parse_program(code)
        found = False
        for declaration in program.declarations:
            if isinstance(declaration, ast.Function) and declaration.name == basename:
                found = True
                bytecode = create_bytecode(declaration.body, args=declaration.params)
                output.write(
                    (", " if index > 0 else "{ ")
                    + f'"{basename}": [{json.dumps(declaration.params)}, {json.dumps(bytecode)}]\n'
                )

        if not found:
            print(f"Error: no function called {basename} was found in {filename}!")  # noqa: T201
            exit(1)

    output.write("}\n")
