import re
from typing import Any, Optional
from collections.abc import Callable

from hogvm.python.operation import Operation, HOGQL_BYTECODE_IDENTIFIER


class HogVMException(Exception):
    pass


def like(string, pattern, flags=0):
    pattern = re.escape(pattern).replace("%", ".*")
    re_pattern = re.compile(pattern, flags)
    return re_pattern.search(string) is not None


def get_nested_value(obj, chain) -> Any:
    if obj is None:
        return None
    for key in chain:
        if isinstance(key, int):
            obj = obj[key]
        else:
            obj = obj.get(key, None)
    return obj


def to_concat_arg(arg) -> str:
    if arg is None:
        return ""
    if arg is True:
        return "true"
    if arg is False:
        return "false"
    return str(arg)


def execute_bytecode(
    bytecode: list[Any],
    fields: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Callable[..., Any]]] = None,
) -> Any:
    try:
        stack = []
        call_stack: list[tuple[int, int, int]] = []  # (ip, stack_start, arg_len)
        declared_functions: dict[str, tuple[int, int]] = {}
        ip = -1

        def next_token():
            nonlocal ip
            if ip >= len(bytecode) - 1:
                return None
            ip += 1
            return bytecode[ip]

        if next_token() != HOGQL_BYTECODE_IDENTIFIER:
            raise HogVMException(f"Invalid bytecode. Must start with '{HOGQL_BYTECODE_IDENTIFIER}'")

        while True:
            symbol = next_token()
            match symbol:
                case None:
                    break
                case Operation.STRING:
                    stack.append(next_token())
                case Operation.INTEGER:
                    stack.append(next_token())
                case Operation.FLOAT:
                    stack.append(next_token())
                case Operation.TRUE:
                    stack.append(True)
                case Operation.FALSE:
                    stack.append(False)
                case Operation.NULL:
                    stack.append(None)
                case Operation.NOT:
                    stack.append(not stack.pop())
                case Operation.AND:
                    stack.append(all([stack.pop() for _ in range(next_token())]))  # noqa: C419
                case Operation.OR:
                    stack.append(any([stack.pop() for _ in range(next_token())]))  # noqa: C419
                case Operation.PLUS:
                    stack.append(stack.pop() + stack.pop())
                case Operation.MINUS:
                    stack.append(stack.pop() - stack.pop())
                case Operation.DIVIDE:
                    stack.append(stack.pop() / stack.pop())
                case Operation.MULTIPLY:
                    stack.append(stack.pop() * stack.pop())
                case Operation.MOD:
                    stack.append(stack.pop() % stack.pop())
                case Operation.EQ:
                    stack.append(stack.pop() == stack.pop())
                case Operation.NOT_EQ:
                    stack.append(stack.pop() != stack.pop())
                case Operation.GT:
                    stack.append(stack.pop() > stack.pop())
                case Operation.GT_EQ:
                    stack.append(stack.pop() >= stack.pop())
                case Operation.LT:
                    stack.append(stack.pop() < stack.pop())
                case Operation.LT_EQ:
                    stack.append(stack.pop() <= stack.pop())
                case Operation.LIKE:
                    stack.append(like(stack.pop(), stack.pop()))
                case Operation.ILIKE:
                    stack.append(like(stack.pop(), stack.pop(), re.IGNORECASE))
                case Operation.NOT_LIKE:
                    stack.append(not like(stack.pop(), stack.pop()))
                case Operation.NOT_ILIKE:
                    stack.append(not like(stack.pop(), stack.pop(), re.IGNORECASE))
                case Operation.IN:
                    stack.append(stack.pop() in stack.pop())
                case Operation.NOT_IN:
                    stack.append(stack.pop() not in stack.pop())
                case Operation.REGEX:
                    args = [stack.pop(), stack.pop()]
                    stack.append(bool(re.search(re.compile(args[1]), args[0])))
                case Operation.NOT_REGEX:
                    args = [stack.pop(), stack.pop()]
                    stack.append(not bool(re.search(re.compile(args[1]), args[0])))
                case Operation.IREGEX:
                    args = [stack.pop(), stack.pop()]
                    stack.append(bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0])))
                case Operation.NOT_IREGEX:
                    args = [stack.pop(), stack.pop()]
                    stack.append(not bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0])))
                case Operation.FIELD:
                    chain = [stack.pop() for _ in range(next_token())]
                    stack.append(get_nested_value(fields, chain))
                case Operation.POP:
                    stack.pop()
                case Operation.RETURN:
                    if call_stack:
                        ip, stack_start, arg_len = call_stack.pop()
                        if arg_len:
                            response = stack.pop()
                            stack = stack[0:stack_start]
                            stack.append(response)
                    else:
                        return stack.pop()
                case Operation.GET_LOCAL:
                    stack_start = 0 if not call_stack else call_stack[-1][1]
                    stack.append(stack[next_token() + stack_start])
                case Operation.SET_LOCAL:
                    stack_start = 0 if not call_stack else call_stack[-1][1]
                    stack[next_token() + stack_start] = stack.pop()
                case Operation.JUMP:
                    count = next_token()
                    ip += count
                case Operation.JUMP_IF_FALSE:
                    count = next_token()
                    if not stack.pop():
                        ip += count
                case Operation.DECLARE_FN:
                    name = next_token()
                    arg_len = next_token()
                    body_len = next_token()
                    declared_functions[name] = (ip, arg_len)
                    ip += body_len
                case Operation.CALL:
                    name = next_token()
                    if name in declared_functions:
                        func_ip, arg_len = declared_functions[name]
                        call_stack.append((ip + 1, len(stack) - arg_len, arg_len))
                        ip = func_ip
                    else:
                        args = [stack.pop() for _ in range(next_token())]
                        if name == "concat":
                            stack.append("".join([to_concat_arg(arg) for arg in args]))
                        elif name == "match":
                            stack.append(bool(re.search(re.compile(args[1]), args[0])))
                        elif name == "toString" or name == "toUUID":
                            if args[0] is True:
                                stack.append("true")
                            elif args[0] is False:
                                stack.append("false")
                            elif args[0] is None:
                                stack.append("null")
                            else:
                                stack.append(str(args[0]))
                        elif name == "toInt" or name == "toFloat":
                            try:
                                stack.append(int(args[0]) if name == "toInt" else float(args[0]))
                            except ValueError:
                                stack.append(None)
                        elif name == "ifNull":
                            if args[0] is not None:
                                stack.append(args[0])
                            else:
                                stack.append(args[1])
                        elif functions is not None and name in functions:
                            stack.append(functions[name](*args))
                        else:
                            raise HogVMException(f"Unsupported function call: {name}")
                case _:
                    raise HogVMException(f"Unexpected node while running bytecode: {symbol}")

        if len(stack) > 1:
            raise HogVMException("Invalid bytecode. More than one value left on stack")

        return stack.pop()
    except IndexError:
        raise HogVMException("Unexpected end of bytecode")
