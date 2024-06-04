import re
from typing import Any, Optional
from collections.abc import Callable
import time

from hogvm.python.operation import Operation, HOGQL_BYTECODE_IDENTIFIER
from hogvm.python.stl import STL
from hogvm.python.vm_utils import HogVMException
from posthog.models import Team
from dataclasses import dataclass


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


def set_nested_value(obj, chain, value) -> Any:
    if obj is None:
        return None
    for key in chain[:-1]:
        if isinstance(key, int):
            obj = obj[key]
        else:
            obj = obj.get(key, None)

    if isinstance(obj, dict):
        obj[chain[-1]] = value
    elif isinstance(obj, list):
        if not isinstance(chain[-1], int):
            raise HogVMException(f"Invalid index: {chain[-1]}")
        obj[chain[-1]] = value
    else:
        raise HogVMException(f'Can not set property "{chain[-1]}" on object of type "{type(obj).__name__}"')

    return obj


@dataclass
class BytecodeResult:
    result: Any
    bytecode: list[Any]
    stdout: list[str]


def execute_bytecode(
    bytecode: list[Any],
    fields: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Callable[..., Any]]] = None,
    timeout=10,
    team: Team | None = None,
) -> BytecodeResult:
    try:
        result = None
        start_time = time.time()
        stack = []
        call_stack: list[tuple[int, int, int]] = []  # (ip, stack_start, arg_len)
        declared_functions: dict[str, tuple[int, int]] = {}
        ip = -1
        ops = 0
        stdout: list[str] = []

        def next_token():
            nonlocal ip
            if ip >= len(bytecode) - 1:
                return None
            ip += 1
            return bytecode[ip]

        if next_token() != HOGQL_BYTECODE_IDENTIFIER:
            raise HogVMException(f"Invalid bytecode. Must start with '{HOGQL_BYTECODE_IDENTIFIER}'")

        def check_timeout():
            if time.time() - start_time > timeout:
                raise HogVMException(f"Execution timed out after {timeout} seconds")

        while True:
            ops += 1
            if (ops & 127) == 0:  # every 128th operation
                check_timeout()
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
                        response = stack.pop()
                        stack = stack[0:stack_start]
                        stack.append(response)
                    else:
                        return BytecodeResult(result=stack.pop(), stdout=stdout, bytecode=bytecode)
                case Operation.GET_LOCAL:
                    stack_start = 0 if not call_stack else call_stack[-1][1]
                    stack.append(stack[next_token() + stack_start])
                case Operation.SET_LOCAL:
                    stack_start = 0 if not call_stack else call_stack[-1][1]
                    stack[next_token() + stack_start] = stack.pop()
                case Operation.GET_PROPERTY:
                    property = stack.pop()
                    stack.append(get_nested_value(stack.pop(), [property]))
                case Operation.SET_PROPERTY:
                    value = stack.pop()
                    field = stack.pop()
                    set_nested_value(stack.pop(), [field], value)
                case Operation.DICT:
                    count = next_token()
                    elems = stack[-(count * 2) :]
                    stack = stack[: -(count * 2)]
                    stack.append({elems[i]: elems[i + 1] for i in range(0, len(elems), 2)})
                case Operation.ARRAY:
                    count = next_token()
                    elems = stack[-count:]
                    stack = stack[:-count]
                    stack.append(elems)
                case Operation.TUPLE:
                    count = next_token()
                    elems = stack[-count:]
                    stack = stack[:-count]
                    stack.append(tuple(elems))
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
                    check_timeout()
                    name = next_token()
                    if name in declared_functions:
                        func_ip, arg_len = declared_functions[name]
                        call_stack.append((ip + 1, len(stack) - arg_len, arg_len))
                        ip = func_ip
                    else:
                        args = [stack.pop() for _ in range(next_token())]

                        if functions is not None and name in functions:
                            stack.append(functions[name](*args))
                            continue

                        if name not in STL:
                            raise HogVMException(f"Unsupported function call: {name}")

                        stack.append(STL[name](name, args, team, stdout, timeout))
                case _:
                    raise HogVMException(f"Unexpected node while running bytecode: {symbol}")

        if len(stack) > 1:
            raise HogVMException("Invalid bytecode. More than one value left on stack")
        if len(stack) == 1:
            result = stack.pop()
        return BytecodeResult(result=result, stdout=stdout, bytecode=bytecode)
    except IndexError:
        raise HogVMException("Unexpected end of bytecode")
