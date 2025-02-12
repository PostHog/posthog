import os
from time import sleep
from typing import Any

from common.hogvm.python.objects import CallFrame
from common.hogvm.python.operation import Operation

debug_speed = -1


def debugger(
    symbol: Any, bytecode: list, colored_bytecode: list, ip: int, stack: list, call_stack: list, throw_stack: list
):
    print("\033[H\033[J", end="")  # noqa: T201

    next_symbol = symbol
    try:
        next_symbol = print_symbol(Operation(next_symbol), ip, bytecode, stack, call_stack)
    except ValueError:
        pass

    top: list = []
    top.append(f"throw_stack: {throw_stack}")  # noqa: T201
    top.append(f"call_stack: {call_stack}")  # noqa: T201
    top.append(f"stack: {stack}")  # noqa: T201
    top.append(f"next: {next_symbol}")  # noqa: T201
    top.append(f"ip: {ip}")  # noqa: T201
    top.append("")  # noqa: T201

    cols = os.get_terminal_size().columns

    # count how much top actually takes
    header_lines = 2
    for line in top:
        header_lines += 1 + len(line) // cols
        print(line)  # noqa: T201

    rows = os.get_terminal_size().lines - header_lines
    rows = 2 if rows < 2 else rows
    rows_from_top = 2 if rows > 2 else 0

    start_ip = max(ip - rows_from_top, 0)
    end_ip = min(start_ip + rows, len(bytecode))
    for i in range(start_ip, end_ip):
        prefix = "> " if i == ip else "  "
        postfix = "" if colored_bytecode[i].startswith("op.") else "    "
        print(f"{prefix}{i}: {postfix}{colored_bytecode[i]}")  # noqa: T201

    global debug_speed
    if debug_speed < 0:
        response = input()
        if response == "help" or response == "h" or response == "?":
            print("- Press <CTRL+C> to quit.")  # noqa: T201
            print("- Press <ENTER> to step to the next instruction.")  # noqa: T201
            print("- Enter a number like 1, 10, 100 or 1000 (ms) to speedwalk the code.")  # noqa: T201
            response = input()
        try:
            debug_speed = int(response)
        except ValueError:
            debug_speed = -1

    else:
        sleep(debug_speed / 1000)


def print_symbol(symbol: Operation, ip: int, bytecode: list, stack: list, call_stack: list[CallFrame]) -> str:
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
            case Operation.GET_GLOBAL:
                return f"GET_GLOBAL({', '.join(str(stack[-i]) for i in range(bytecode[ip+1]))})"
            case Operation.POP:
                return f"POP({stack[-1]})"
            case Operation.RETURN:
                if len(call_stack) > 1:
                    return f"RETURN({stack[-1]}) --> {call_stack[-2].ip}"
                else:
                    return "RETURN"
            case Operation.GET_LOCAL:
                return f"GET_LOCAL({bytecode[ip+1]})"
            case Operation.SET_LOCAL:
                return f"SET_LOCAL({bytecode[ip + 1]}, {stack[-1]})"
            case Operation.GET_UPVALUE:
                return f"GET_UPVALUE({bytecode[ip+1]})"
            case Operation.SET_UPVALUE:
                return f"SET_UPVALUE({bytecode[ip + 1]})"
            case Operation.CLOSE_UPVALUE:
                return "CLOSE_UPVALUE"
            case Operation.GET_PROPERTY:
                return f"GET_PROPERTY({stack[-2]}, {stack[-1]})"
            case Operation.GET_PROPERTY_NULLISH:
                return f"GET_PROPERTY_NULLISH({stack[-2]}, {stack[-1]})"
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
            case Operation.JUMP_IF_STACK_NOT_NULL:
                return (
                    f"JUMP_IF_STACK_NOT_NULL({'+' if bytecode[ip+1] >= 0 else ''}{bytecode[ip+1]}, {bool(stack[-1])})"
                )
            case Operation.DECLARE_FN:
                return f"DECLARE_FN({bytecode[ip+1]}, args={bytecode[ip+2]}, ops={bytecode[ip+3]})"
            case Operation.CALLABLE:
                return f"CALLABLE({bytecode[ip+1]}, args={bytecode[ip+2]}, upvalues={bytecode[ip+3]}, ops={bytecode[ip+4]})"
            case Operation.CLOSURE:
                return f"CLOSURE"
            case Operation.CALL_GLOBAL:
                return f"CALL_GLOBAL({bytecode[ip+1]}, {', '.join(str(stack[-(bytecode[ip+2] - i)]) for i in range(bytecode[ip+2]))})"
            case Operation.CALL_LOCAL:
                return f"CALL_LOCAL({bytecode[ip+1]} {', '.join(str(stack[-(bytecode[ip+1] - i)]) for i in range(bytecode[ip+1]))})"
            case Operation.TRY:
                return f"TRY(+{bytecode[ip+1]})"
            case Operation.POP_TRY:
                return "POP_TRY"
            case Operation.THROW:
                return f"THROW({stack[-1]})"
        return symbol.name
    except Exception as e:
        return f"{symbol.name}(ERROR: {e})"


def color_bytecode(bytecode: list) -> list:
    colored = ["op.START", f"version: {bytecode[1]}"] if bytecode[0] == "_H" else ["op.START"]
    ip = len(colored)
    while ip < len(bytecode):
        symbol = bytecode[ip]
        match symbol:
            case Operation.STRING:
                add = ["op.STRING", f"string: {bytecode[ip+1]}"]
            case Operation.INTEGER:
                add = ["op.INTEGER", f"integer: {bytecode[ip+1]}"]
            case Operation.FLOAT:
                add = ["op.FLOAT", f"float: {bytecode[ip+1]}"]
            case Operation.TRUE:
                add = ["op.TRUE"]
            case Operation.FALSE:
                add = ["op.FALSE"]
            case Operation.NULL:
                add = ["op.NULL"]
            case Operation.NOT:
                add = ["op.NOT"]
            case Operation.AND:
                add = ["op.AND", f"expr count: {bytecode[ip+1]}"]
            case Operation.OR:
                add = ["op.OR", f"expr count: {bytecode[ip+1]}"]
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
            case Operation.GET_GLOBAL:
                add = ["op.GET_GLOBAL", f"field count: {bytecode[ip+1]}"]
            case Operation.POP:
                add = ["op.POP"]
            case Operation.RETURN:
                add = ["op.RETURN"]
            case Operation.GET_LOCAL:
                add = ["op.GET_LOCAL", f"index: {bytecode[ip+1]}"]
            case Operation.SET_LOCAL:
                add = ["op.SET_LOCAL", f"index: {bytecode[ip+1]}"]
            case Operation.GET_UPVALUE:
                add = ["op.GET_UPVALUE", f"index: {bytecode[ip+1]}"]
            case Operation.SET_UPVALUE:
                add = ["op.SET_UPVALUE", f"index: {bytecode[ip+1]}"]
            case Operation.CLOSE_UPVALUE:
                add = ["op.CLOSE_UPVALUE"]
            case Operation.GET_PROPERTY:
                add = ["op.GET_PROPERTY"]
            case Operation.GET_PROPERTY_NULLISH:
                add = ["op.GET_PROPERTY_NULLISH"]
            case Operation.SET_PROPERTY:
                add = ["op.SET_PROPERTY"]
            case Operation.DICT:
                add = ["op.DICT", f"key count: {bytecode[ip+1]}"]
            case Operation.ARRAY:
                add = ["op.ARRAY", f"element count: {bytecode[ip+1]}"]
            case Operation.TUPLE:
                add = ["op.TUPLE", f"element count: {bytecode[ip+1]}"]
            case Operation.JUMP:
                add = ["op.JUMP", f"offset: {'+' if bytecode[ip+1] >= 0 else ''}{bytecode[ip+1]}"]
            case Operation.JUMP_IF_FALSE:
                add = ["op.JUMP_IF_FALSE", f"offset: {'+' if bytecode[ip+1] >= 0 else ''}{bytecode[ip+1]}"]
            case Operation.JUMP_IF_STACK_NOT_NULL:
                add = ["op.JUMP_IF_STACK_NOT_NULL", f"offset: {'+' if bytecode[ip+1] >= 0 else ''}{bytecode[ip+1]}"]
            case Operation.DECLARE_FN:
                add = ["op.DECLARE_FN", f"name: {bytecode[ip+1]}", f"args: {bytecode[ip+2]}", f"ops: {bytecode[ip+3]}"]
            case Operation.CALLABLE:
                add = [
                    "op.CALLABLE",
                    f"name: {bytecode[ip+1]}",
                    f"args: {bytecode[ip+2]}",
                    f"upvalues: {bytecode[ip+3]}",
                    f"ops: {bytecode[ip+4]}",
                ]
            case Operation.CLOSURE:
                upvalue_count = bytecode[ip + 1]
                add = ["op.CLOSURE", f"upvalues: {upvalue_count}"]
                for i in range(upvalue_count):
                    add.append(f"is_local({i}): {bytecode[ip + 2 + i * 2]}")
                    add.append(f"index({i}): {bytecode[ip + 2 + i * 2 + 1]}")
            case Operation.CALL_LOCAL:
                add = ["op.CALL_LOCAL", f"args: {bytecode[ip+1]}"]
            case Operation.CALL_GLOBAL:
                add = ["op.CALL_GLOBAL", f"name: {bytecode[ip+1]}", f"args: {bytecode[ip+2]}"]
            case Operation.TRY:
                add = ["op.TRY", f"catch: +{bytecode[ip+1]}"]
            case Operation.POP_TRY:
                add = ["op.POP_TRY"]
            case Operation.THROW:
                add = ["op.THROW"]
            case _:
                add = [f"ERROR: Unknown bytecode {symbol}"]
        colored.extend(add)
        ip += len(add)
    return colored
