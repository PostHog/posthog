# HogE, the "HOG compilEr", is a tool that compiles ".hog" programs into ".hoge" bytecode.

import sys
import json
from .bytecode import create_bytecode, parse_program

# get filename from first cli arg
filename = sys.argv[1]

# raise if filename does not end with ".hog"
if not filename.endswith(".hog"):
    raise ValueError("filename must end with '.hog'")

# read file
with open(filename) as file:
    code = file.read()

# execute code
bytecode = create_bytecode(parse_program(code))

# write bytecode to file
with open(filename[:-4] + ".hoge", "w") as file:
    max_length = 120
    line = "["
    for index, op in enumerate(bytecode):
        encoded = json.dumps(op)
        if len(line) + len(encoded) > max_length - 2:
            file.write(line + "\n")
            line = ""
        line += (" " if len(line) > 0 else "") + encoded + ("]" if index == len(bytecode) - 1 else ",")
    if line == "[":
        file.write(line + "]\n")
    elif line != "":
        file.write(line + "\n")
