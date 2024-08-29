import sys
import json

from hogvm.python.execute import execute_bytecode
from .bytecode import create_bytecode, parse_program

modifiers = [arg for arg in sys.argv if arg.startswith("-")]
args = [arg for arg in sys.argv if arg != "" and not arg.startswith("-")]
filename = args[1]

if not filename.endswith(".hog") and not filename.endswith(".hoge"):
    raise ValueError("Filename must end with '.hog' or '.hoge'")

with open(filename) as file:
    code = file.read()

if filename.endswith(".hog"):
    bytecode = create_bytecode(parse_program(code))
else:
    bytecode = json.loads(code)

if "--run" in modifiers:
    if len(args) != 2:
        raise ValueError("Must specify exactly one filename")

    response = execute_bytecode(bytecode, globals=None, timeout=5, team=None, debug="--debug" in modifiers)
    for line in response.stdout:
        print(line)  # noqa: T201

elif "--out" in modifiers:
    if len(args) != 2:
        raise ValueError("Must specify exactly one filename")
    print(json.dumps(bytecode))  # noqa: T201

elif "--compile" in modifiers:
    if len(args) == 3:
        target = args[2]
    else:
        target = filename[:-4] + ".hoge"
        if len(args) != 2:
            raise ValueError("Must specify exactly one filename")

    # write bytecode to file
    with open(target, "w") as file:
        max_length = 120
        line = "["
        for index, op in enumerate(bytecode):
            encoded = json.dumps(op)
            if len(line) + len(encoded) > max_length - 2:
                file.write(line + "\n")
                line = ""
            line += (" " if len(line) > 1 else "") + encoded + ("]" if index == len(bytecode) - 1 else ",")
        if line == "[":
            file.write(line + "]\n")
        elif line != "":
            file.write(line + "\n")

else:
    raise ValueError("Must specify either --run or --compile")
