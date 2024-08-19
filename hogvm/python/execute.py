from datetime import timedelta
import re
import time
from copy import deepcopy
from typing import Any, Optional, TYPE_CHECKING
from collections.abc import Callable

from hogvm.python.debugger import debugger, color_bytecode
from hogvm.python.objects import is_hog_error
from hogvm.python.operation import Operation, HOGQL_BYTECODE_IDENTIFIER
from hogvm.python.stl import STL
from dataclasses import dataclass

from hogvm.python.utils import (
    UncaughtHogVMException,
    HogVMException,
    get_nested_value,
    like,
    set_nested_value,
    calculate_cost,
)

if TYPE_CHECKING:
    from posthog.models import Team

MAX_MEMORY = 64 * 1024 * 1024  # 64 MB


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
    mem_stack: list = []
    call_stack: list[tuple[int, int, int]] = []  # (ip, stack_start, arg_len)
    throw_stack: list[tuple[int, int, int]] = []  # (call_stack_length, stack_length, catch_ip)
    declared_functions: dict[str, tuple[int, int]] = {}
    mem_used = 0
    max_mem_used = 0
    ip = -1
    ops = 0
    stdout: list[str] = []
    colored_bytecode = color_bytecode(bytecode) if debug else []
    if isinstance(timeout, int):
        timeout = timedelta(seconds=timeout)

    def next_token():
        nonlocal ip
        ip += 1
        if ip > last_op:
            raise HogVMException("Unexpected end of bytecode")
        return bytecode[ip]

    def pop_stack():
        if not stack:
            raise HogVMException("Stack underflow")
        nonlocal mem_used
        mem_used -= mem_stack.pop()
        return stack.pop()

    def push_stack(value):
        stack.append(value)
        mem_stack.append(calculate_cost(value))
        nonlocal mem_used
        mem_used += mem_stack[-1]
        nonlocal max_mem_used
        max_mem_used = max(mem_used, max_mem_used)
        if mem_used > MAX_MEMORY:
            raise HogVMException(f"Memory limit of {MAX_MEMORY} bytes exceeded. Tried to allocate {mem_used} bytes.")

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
            debugger(symbol, bytecode, colored_bytecode, ip, stack, call_stack, throw_stack)
        match symbol:
            case None:
                break
            case Operation.STRING:
                push_stack(next_token())
            case Operation.INTEGER:
                push_stack(next_token())
            case Operation.FLOAT:
                push_stack(next_token())
            case Operation.TRUE:
                push_stack(True)
            case Operation.FALSE:
                push_stack(False)
            case Operation.NULL:
                push_stack(None)
            case Operation.NOT:
                push_stack(not pop_stack())
            case Operation.AND:
                push_stack(all([pop_stack() for _ in range(next_token())]))  # noqa: C419
            case Operation.OR:
                push_stack(any([pop_stack() for _ in range(next_token())]))  # noqa: C419
            case Operation.PLUS:
                push_stack(pop_stack() + pop_stack())
            case Operation.MINUS:
                push_stack(pop_stack() - pop_stack())
            case Operation.DIVIDE:
                push_stack(pop_stack() / pop_stack())
            case Operation.MULTIPLY:
                push_stack(pop_stack() * pop_stack())
            case Operation.MOD:
                push_stack(pop_stack() % pop_stack())
            case Operation.EQ:
                push_stack(pop_stack() == pop_stack())
            case Operation.NOT_EQ:
                push_stack(pop_stack() != pop_stack())
            case Operation.GT:
                push_stack(pop_stack() > pop_stack())
            case Operation.GT_EQ:
                push_stack(pop_stack() >= pop_stack())
            case Operation.LT:
                push_stack(pop_stack() < pop_stack())
            case Operation.LT_EQ:
                push_stack(pop_stack() <= pop_stack())
            case Operation.LIKE:
                push_stack(like(pop_stack(), pop_stack()))
            case Operation.ILIKE:
                push_stack(like(pop_stack(), pop_stack(), re.IGNORECASE))
            case Operation.NOT_LIKE:
                push_stack(not like(pop_stack(), pop_stack()))
            case Operation.NOT_ILIKE:
                push_stack(not like(pop_stack(), pop_stack(), re.IGNORECASE))
            case Operation.IN:
                push_stack(pop_stack() in pop_stack())
            case Operation.NOT_IN:
                push_stack(pop_stack() not in pop_stack())
            case Operation.REGEX:
                args = [pop_stack(), pop_stack()]
                # TODO: swap this for re2, as used in HogQL/ClickHouse and in the NodeJS VM
                push_stack(bool(re.search(re.compile(args[1]), args[0])))
            case Operation.NOT_REGEX:
                args = [pop_stack(), pop_stack()]
                # TODO: swap this for re2, as used in HogQL/ClickHouse and in the NodeJS VM
                push_stack(not bool(re.search(re.compile(args[1]), args[0])))
            case Operation.IREGEX:
                args = [pop_stack(), pop_stack()]
                push_stack(bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0])))
            case Operation.NOT_IREGEX:
                args = [pop_stack(), pop_stack()]
                push_stack(not bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0])))
            case Operation.GET_GLOBAL:
                chain = [pop_stack() for _ in range(next_token())]
                push_stack(deepcopy(get_nested_value(globals, chain)))
            case Operation.POP:
                pop_stack()
            case Operation.RETURN:
                if call_stack:
                    ip, stack_start, arg_len = call_stack.pop()
                    response = pop_stack()
                    stack = stack[0:stack_start]
                    mem_used -= sum(mem_stack[stack_start:])
                    mem_stack = mem_stack[0:stack_start]
                    push_stack(response)
                else:
                    return BytecodeResult(result=pop_stack(), stdout=stdout, bytecode=bytecode)
            case Operation.GET_LOCAL:
                stack_start = 0 if not call_stack else call_stack[-1][1]
                push_stack(stack[next_token() + stack_start])
            case Operation.SET_LOCAL:
                stack_start = 0 if not call_stack else call_stack[-1][1]
                value = pop_stack()
                index = next_token() + stack_start
                stack[index] = value
                last_cost = mem_stack[index]
                mem_stack[index] = calculate_cost(value)
                mem_used += mem_stack[index] - last_cost
                max_mem_used = max(mem_used, max_mem_used)
            case Operation.GET_PROPERTY:
                property = pop_stack()
                push_stack(get_nested_value(pop_stack(), [property]))
            case Operation.GET_PROPERTY_NULLISH:
                property = pop_stack()
                push_stack(get_nested_value(pop_stack(), [property], nullish=True))
            case Operation.SET_PROPERTY:
                value = pop_stack()
                field = pop_stack()
                set_nested_value(pop_stack(), [field], value)
            case Operation.DICT:
                count = next_token()
                if count > 0:
                    elems = stack[-(count * 2) :]
                    stack = stack[: -(count * 2)]
                    mem_used -= sum(mem_stack[-(count * 2) :])
                    mem_stack = mem_stack[: -(count * 2)]
                    push_stack({elems[i]: elems[i + 1] for i in range(0, len(elems), 2)})
                else:
                    push_stack({})
            case Operation.ARRAY:
                count = next_token()
                if count > 0:
                    elems = stack[-count:]
                    stack = stack[:-count]
                    mem_used -= sum(mem_stack[-count:])
                    mem_stack = mem_stack[:-count]
                    push_stack(elems)
                else:
                    push_stack([])
            case Operation.TUPLE:
                count = next_token()
                if count > 0:
                    elems = stack[-count:]
                    stack = stack[:-count]
                    mem_used -= sum(mem_stack[-count:])
                    mem_stack = mem_stack[:-count]
                    push_stack(tuple(elems))
                else:
                    push_stack(())
            case Operation.JUMP:
                count = next_token()
                ip += count
            case Operation.JUMP_IF_FALSE:
                count = next_token()
                if not pop_stack():
                    ip += count
            case Operation.JUMP_IF_STACK_NOT_NULL:
                count = next_token()
                if len(stack) > 0 and stack[-1] is not None:
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
                        push_stack(functions[name](*args))
                        continue

                    if name not in STL:
                        raise HogVMException(f"Unsupported function call: {name}")

                    push_stack(STL[name](args, team, stdout, timeout.total_seconds()))
            case Operation.TRY:
                throw_stack.append((len(call_stack), len(stack), ip + next_token()))
            case Operation.POP_TRY:
                if throw_stack:
                    throw_stack.pop()
                else:
                    raise HogVMException("Invalid operation POP_TRY: no try block to pop")
            case Operation.THROW:
                exception = pop_stack()
                if not is_hog_error(exception):
                    raise HogVMException("Can not throw: value is not of type Error")
                if throw_stack:
                    call_stack_len, stack_len, catch_ip = throw_stack.pop()
                    stack = stack[0:stack_len]
                    mem_used -= sum(mem_stack[stack_len:])
                    mem_stack = mem_stack[0:stack_len]
                    call_stack = call_stack[0:call_stack_len]
                    push_stack(exception)
                    ip = catch_ip
                else:
                    raise UncaughtHogVMException(
                        type=exception.get("type"),
                        message=exception.get("message"),
                        payload=exception.get("payload"),
                    )

        if ip == last_op:
            break
    if debug:
        debugger(symbol, bytecode, colored_bytecode, ip, stack, call_stack, throw_stack)
    if len(stack) > 1:
        raise HogVMException("Invalid bytecode. More than one value left on stack")
    if len(stack) == 1:
        result = pop_stack()
    return BytecodeResult(result=result, stdout=stdout, bytecode=bytecode)
