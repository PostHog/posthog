from typing import Any
import re
from hogvm.python.utils import HogVMException


def _to_concat_arg(arg) -> str:
    if arg is None:
        return ""
    if arg is True:
        return "true"
    if arg is False:
        return "false"
    return str(arg)


def execute_stl_function(name: str, args: list[Any], stack: list[Any]):
    match name:
        case "concat":
            stack.append("".join([_to_concat_arg(arg) for arg in args]))
        case "match":
            stack.append(bool(re.search(re.compile(args[1]), args[0])))
        case "toString" | "toUUID":
            if args[0] is True:
                stack.append("true")
            elif args[0] is False:
                stack.append("false")
            elif args[0] is None:
                stack.append("null")
            else:
                stack.append(str(args[0]))
        case "toInt" | "toFloat":
            try:
                stack.append(int(args[0]) if name == "toInt" else float(args[0]))
            except ValueError:
                stack.append(None)
        case "ifNull":
            if args[0] is not None:
                stack.append(args[0])
            else:
                stack.append(args[1])
        case "length":
            stack.append(len(args[0]))
        case "empty":
            stack.append(not bool(args[0]))
        case "notEmpty":
            stack.append(bool(args[0]))
        case "lower":
            stack.append(args[0].lower())
        case "upper":
            stack.append(args[0].upper())
        case "reverse":
            stack.append(args[0][::-1])
        case _:
            raise HogVMException(f"Unsupported function call: {name}")
