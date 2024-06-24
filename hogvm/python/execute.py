from datetime import timedelta
import re
import time
from copy import deepcopy
from typing import Any, Optional, TYPE_CHECKING
from collections.abc import Callable

from hogvm.python.debugger import debugger, color_bytecode
from hogvm.python.operation import Operation, HOGQL_BYTECODE_IDENTIFIER
from hogvm.python.stl import STL
from dataclasses import dataclass

from hogvm.python.utils import HogVMException, get_nested_value, like, set_nested_value

if TYPE_CHECKING:
    from posthog.models import Team


@dataclass
class BytecodeResult:
    result: Any
    bytecode: list[Any]
    stdout: list[str]


def execute_bytecode(
    bytecode: list[Any],
    globals: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Callable[..., Any]]] = None,
    timeout=timedelta(seconds=5),
    team: Optional["Team"] = None,
    debug=False,
) -> BytecodeResult:
    result = None
    start_time = time.time()
    last_op = len(bytecode) - 1
    stack: list = []
    call_stack: list[tuple[int, int, int]] = []  # (ip, stack_start, arg_len)
    declared_functions: dict[str, tuple[int, int]] = {}
    ip = -1
    ops = 0
    stdout: list[str] = []
    colored_bytecode = color_bytecode(bytecode) if debug else []

    def next_token():
        nonlocal ip
        ip += 1
        if ip > last_op:
            raise HogVMException("Unexpected end of bytecode")
        return bytecode[ip]

    def pop_stack():
        if not stack:
            raise HogVMException("Stack underflow")
        return stack.pop()

    if next_token() != HOGQL_BYTECODE_IDENTIFIER:
        raise HogVMException(f"Invalid bytecode. Must start with '{HOGQL_BYTECODE_IDENTIFIER}'")

    if len(bytecode) == 1:
        return BytecodeResult(result=None, stdout=stdout, bytecode=bytecode)

    def check_timeout():
        if time.time() - start_time > timeout.total_seconds() and not debug:
            raise HogVMException(f"Execution timed out after {timeout.total_seconds()} seconds. Performed {ops} ops.")

    while True:
        ops += 1
        symbol = next_token()
        if (ops & 127) == 0:  # every 128th operation
            check_timeout()
        elif debug:
            debugger(symbol, bytecode, colored_bytecode, ip, stack, call_stack)
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
                stack.append(not pop_stack())
            case Operation.AND:
                stack.append(all([pop_stack() for _ in range(next_token())]))  # noqa: C419
            case Operation.OR:
                stack.append(any([pop_stack() for _ in range(next_token())]))  # noqa: C419
            case Operation.PLUS:
                stack.append(pop_stack() + pop_stack())
            case Operation.MINUS:
                stack.append(pop_stack() - pop_stack())
            case Operation.DIVIDE:
                stack.append(pop_stack() / pop_stack())
            case Operation.MULTIPLY:
                stack.append(pop_stack() * pop_stack())
            case Operation.MOD:
                stack.append(pop_stack() % pop_stack())
            case Operation.EQ:
                stack.append(pop_stack() == pop_stack())
            case Operation.NOT_EQ:
                stack.append(pop_stack() != pop_stack())
            case Operation.GT:
                stack.append(pop_stack() > pop_stack())
            case Operation.GT_EQ:
                stack.append(pop_stack() >= pop_stack())
            case Operation.LT:
                stack.append(pop_stack() < pop_stack())
            case Operation.LT_EQ:
                stack.append(pop_stack() <= pop_stack())
            case Operation.LIKE:
                stack.append(like(pop_stack(), pop_stack()))
            case Operation.ILIKE:
                stack.append(like(pop_stack(), pop_stack(), re.IGNORECASE))
            case Operation.NOT_LIKE:
                stack.append(not like(pop_stack(), pop_stack()))
            case Operation.NOT_ILIKE:
                stack.append(not like(pop_stack(), pop_stack(), re.IGNORECASE))
            case Operation.IN:
                stack.append(pop_stack() in pop_stack())
            case Operation.NOT_IN:
                stack.append(pop_stack() not in pop_stack())
            case Operation.REGEX:
                args = [pop_stack(), pop_stack()]
                stack.append(bool(re.search(re.compile(args[1]), args[0])))
            case Operation.NOT_REGEX:
                args = [pop_stack(), pop_stack()]
                stack.append(not bool(re.search(re.compile(args[1]), args[0])))
            case Operation.IREGEX:
                args = [pop_stack(), pop_stack()]
                stack.append(bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0])))
            case Operation.NOT_IREGEX:
                args = [pop_stack(), pop_stack()]
                stack.append(not bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0])))
            case Operation.GET_GLOBAL:
                chain = [pop_stack() for _ in range(next_token())]
                stack.append(deepcopy(get_nested_value(globals, chain)))
            case Operation.POP:
                pop_stack()
            case Operation.RETURN:
                if call_stack:
                    ip, stack_start, arg_len = call_stack.pop()
                    response = pop_stack()
                    stack = stack[0:stack_start]
                    stack.append(response)
                else:
                    return BytecodeResult(result=pop_stack(), stdout=stdout, bytecode=bytecode)
            case Operation.GET_LOCAL:
                stack_start = 0 if not call_stack else call_stack[-1][1]
                stack.append(stack[next_token() + stack_start])
            case Operation.SET_LOCAL:
                stack_start = 0 if not call_stack else call_stack[-1][1]
                value = pop_stack()
                stack[next_token() + stack_start] = value
            case Operation.GET_PROPERTY:
                property = pop_stack()
                stack.append(get_nested_value(pop_stack(), [property]))
            case Operation.SET_PROPERTY:
                value = pop_stack()
                field = pop_stack()
                set_nested_value(pop_stack(), [field], value)
            case Operation.DICT:
                count = next_token()
                if count > 0:
                    elems = stack[-(count * 2) :]
                    stack = stack[: -(count * 2)]
                    stack.append({elems[i]: elems[i + 1] for i in range(0, len(elems), 2)})
                else:
                    stack.append({})
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
                if not pop_stack():
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
                    args = [pop_stack() for _ in range(next_token())]

                    if functions is not None and name in functions:
                        stack.append(functions[name](*args))
                        continue

                    if name not in STL:
                        raise HogVMException(f"Unsupported function call: {name}")

                    stack.append(STL[name](name, args, team, stdout, timeout))
        if ip == last_op:
            break
    if debug:
        debugger(symbol, bytecode, colored_bytecode, ip, stack, call_stack)
    if len(stack) > 1:
        raise HogVMException("Invalid bytecode. More than one value left on stack")
    if len(stack) == 1:
        result = pop_stack()
    return BytecodeResult(result=result, stdout=stdout, bytecode=bytecode)
