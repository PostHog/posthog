import os
from typing import Any

from hogvm.python.operation import Operation


def debugger(symbol: Any, bytecode: list, colored_bytecode: list, ip: int, stack: list, call_stack: list):
    rows = os.get_terminal_size().lines - 6
    rows = 2 if rows < 2 else rows
    rows_from_top = 2 if rows > 2 else 0
    next_symbol = symbol
    try:
        next_symbol = print_symbol(Operation(next_symbol), ip, bytecode, stack, call_stack)
    except ValueError:
        pass
    print("\033[H\033[J", end="")  # noqa: T201
    print(f"call_stack: {call_stack}")  # noqa: T201
    print(f"stack: {stack}")  # noqa: T201
    print(f"next: {next_symbol}")  # noqa: T201
    print(f"ip: {ip}")  # noqa: T201
    print("")  # noqa: T201

    start_ip = ip - rows_from_top if ip > rows_from_top else 0
    end_ip = len(bytecode) if start_ip + rows > len(bytecode) else (start_ip + rows)
    for i, op in enumerate(bytecode[start_ip:end_ip], start=start_ip):
        if i == 0 or (colored_bytecode[i] or "").startswith("op."):
            line = f"{colored_bytecode[i]}"
        else:
            line = f"    {colored_bytecode[i]}: {op}"
        if i == ip:
            print(f"> {i}: {line}")  # noqa: T201
        else:
            print(f"  {i}: {line}")  # noqa: T201
    input()


def print_symbol(symbol: Operation, ip: int, bytecode: list, stack: list, call_stack: list) -> str:
    try:
        match symbol:
            case Operation.STRING:
                return f"STRING({bytecode[ip+1]})"
            case Operation.INTEGER:
                return f"INTEGER({bytecode[ip+1]})"
            case Operation.FLOAT:
                return f"FLOAT({bytecode[ip+1]})"
            case Operation.TRUE:
                return "TRUE"
            case Operation.FALSE:
                return "FALSE"
            case Operation.NULL:
                return "NULL"
            case Operation.NOT:
                return f"NOT({stack[-1]})"
            case Operation.AND:
                return f"AND({', '.join(str(stack[-i]) for i in range(bytecode[ip+1]))})"
            case Operation.OR:
                return f"OR({', '.join(str(stack[-i]) for i in range(bytecode[ip+1]))})"
            case Operation.PLUS:
                return f"PLUS({stack[-2]}, {stack[-1]})"
            case Operation.MINUS:
                return f"MINUS({stack[-2]}, {stack[-1]})"
            case Operation.MULTIPLY:
                return f"MULTIPLY({stack[-2]}, {stack[-1]})"
            case Operation.DIVIDE:
                return f"DIVIDE({stack[-2]}, {stack[-1]})"
            case Operation.EQ:
                return f"EQ({stack[-2]}, {stack[-1]})"
            case Operation.NOT_EQ:
                return f"NOT_EQ({stack[-2]}, {stack[-1]})"
            case Operation.GT:
                return f"GT({stack[-2]}, {stack[-1]})"
            case Operation.GT_EQ:
                return f"GT_EQ({stack[-2]}, {stack[-1]})"
            case Operation.LT:
                return f"LT({stack[-2]}, {stack[-1]})"
            case Operation.LT_EQ:
                return f"LT_EQ({stack[-2]}, {stack[-1]})"
            case Operation.LIKE:
                return f"LIKE({stack[-2]}, {stack[-1]})"
            case Operation.ILIKE:
                return f"ILIKE({stack[-2]}, {stack[-1]})"
            case Operation.NOT_LIKE:
                return f"NOT_LIKE({stack[-2]}, {stack[-1]})"
            case Operation.NOT_ILIKE:
                return f"NOT_ILIKE({stack[-2]}, {stack[-1]})"
            case Operation.IN:
                return f"IN({stack[-2]}, {stack[-1]})"
            case Operation.NOT_IN:
                return f"NOT_IN({stack[-2]}, {stack[-1]})"
            case Operation.REGEX:
                return f"REGEX({stack[-2]}, {stack[-1]})"
            case Operation.NOT_REGEX:
                return f"NOT_REGEX({stack[-2]}, {stack[-1]})"
            case Operation.IREGEX:
                return f"IREGEX({stack[-2]}, {stack[-1]})"
            case Operation.NOT_IREGEX:
                return f"NOT_IREGEX({stack[-2]}, {stack[-1]})"
            case Operation.IN_COHORT:
                return f"IN_COHORT({stack[-2]}, {stack[-1]})"
            case Operation.NOT_IN_COHORT:
                return f"NOT_IN_COHORT({stack[-2]}, {stack[-1]})"
            case Operation.FIELD:
                return f"FIELD({', '.join(str(stack[-i]) for i in range(bytecode[ip+1]))})"
            case Operation.POP:
                return f"POP({stack[-1]})"
            case Operation.RETURN:
                if call_stack:
                    ip, stack_start, arg_len = call_stack[-1]
                    return f"RETURN({stack[-1]} --> {ip}/{stack_start})"
                else:
                    return "RETURN"
            case Operation.GET_LOCAL:
                return f"GET_LOCAL({bytecode[ip+1]})"
            case Operation.SET_LOCAL:
                return f"GET_LOCAL({bytecode[ip + 1]}, {stack[-1]})"
            case Operation.GET_PROPERTY:
                return f"GET_PROPERTY({stack[-2]}, {stack[-1]})"
            case Operation.SET_PROPERTY:
                return f"SET_PROPERTY({stack[-3]}, {stack[-2]}, {stack[-1]})"
            case Operation.DICT:
                return f"DICT({bytecode[ip+1]})"
            case Operation.ARRAY:
                return f"ARRAY({bytecode[ip+1]})"
            case Operation.TUPLE:
                return f"TUPLE({bytecode[ip+1]})"
            case Operation.JUMP:
                return f"JUMP({'+' if bytecode[ip+1] >= 0 else ''}{bytecode[ip+1]})"
            case Operation.JUMP_IF_FALSE:
                return f"JUMP_IF_FALSE({'+' if bytecode[ip+1] >= 0 else ''}{bytecode[ip+1]}, {bool(stack[-1])})"
            case Operation.DECLARE_FN:
                return f"DECLARE_FN({bytecode[ip+1]}, args={bytecode[ip+2]}, ops={bytecode[ip+3]})"
            case Operation.CALL:
                return f"CALL({bytecode[ip+1]} {', '.join(str(stack[-i]) for i in range(bytecode[ip+2]))})"
        return symbol.name
    except Exception as e:
        return f"{symbol.name}(ERROR: {e})"


def color_bytecode(bytecode: list) -> list:
    colored = ["START"]
    ip = 1
    while ip < len(bytecode):
        symbol = bytecode[ip]
        match symbol:
            case Operation.STRING:
                add = ["op.STRING", "string"]
            case Operation.INTEGER:
                add = ["op.INTEGER", "integer"]
            case Operation.FLOAT:
                add = ["op.FLOAT", "float"]
            case Operation.TRUE:
                add = ["op.TRUE"]
            case Operation.FALSE:
                add = ["op.FALSE"]
            case Operation.NULL:
                add = ["op.NULL"]
            case Operation.NOT:
                add = ["op.NOT"]
            case Operation.AND:
                add = ["op.AND", "expr count"]
            case Operation.OR:
                add = ["op.OR", "expr count"]
            case Operation.PLUS:
                add = ["op.PLUS"]
            case Operation.MINUS:
                add = ["op.MINUS"]
            case Operation.MULTIPLY:
                add = ["op.MULTIPLY"]
            case Operation.DIVIDE:
                add = ["op.DIVIDE"]
            case Operation.EQ:
                add = ["op.EQ"]
            case Operation.NOT_EQ:
                add = ["op.NOT_EQ"]
            case Operation.GT:
                add = ["op.GT"]
            case Operation.GT_EQ:
                add = ["op.GT_EQ"]
            case Operation.LT:
                add = ["op.LT"]
            case Operation.LT_EQ:
                add = ["op.LT_EQ"]
            case Operation.LIKE:
                add = ["op.LIKE"]
            case Operation.ILIKE:
                add = ["op.ILIKE"]
            case Operation.NOT_LIKE:
                add = ["op.NOT_LIKE"]
            case Operation.NOT_ILIKE:
                add = ["op.NOT_ILIKE"]
            case Operation.IN:
                add = ["op.IN"]
            case Operation.NOT_IN:
                add = ["op.NOT_IN"]
            case Operation.REGEX:
                add = ["op.REGEX"]
            case Operation.NOT_REGEX:
                add = ["op.NOT_REGEX"]
            case Operation.IREGEX:
                add = ["op.IREGEX"]
            case Operation.NOT_IREGEX:
                add = ["op.NOT_IREGEX"]
            case Operation.IN_COHORT:
                add = ["op.IN_COHORT"]
            case Operation.NOT_IN_COHORT:
                add = ["op.NOT_IN_COHORT"]
            case Operation.FIELD:
                add = ["op.FIELD", "field count"]
            case Operation.POP:
                add = ["op.POP"]
            case Operation.RETURN:
                add = ["op.RETURN"]
            case Operation.GET_LOCAL:
                add = ["op.GET_LOCAL", "index"]
            case Operation.SET_LOCAL:
                add = ["op.SET_LOCAL", "index"]
            case Operation.GET_PROPERTY:
                add = ["op.GET_PROPERTY"]
            case Operation.SET_PROPERTY:
                add = ["op.SET_PROPERTY"]
            case Operation.DICT:
                add = ["op.DICT", "key count"]
            case Operation.ARRAY:
                add = ["op.ARRAY", "element count"]
            case Operation.TUPLE:
                add = ["op.TUPLE", "element count"]
            case Operation.JUMP:
                add = ["op.JUMP", "offset"]
            case Operation.JUMP_IF_FALSE:
                add = ["op.JUMP_IF_FALSE", "offset"]
            case Operation.DECLARE_FN:
                add = ["op.DECLARE_FN", "name", "args", "ops"]
            case Operation.CALL:
                add = ["op.CALL", "name", "args"]
            case _:
                add = ["ERROR"]
        colored.extend(add)
        ip += len(add)
    return colored
