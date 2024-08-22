from datetime import timedelta
import re
import time
from copy import deepcopy
from typing import Any, Optional, TYPE_CHECKING
from collections.abc import Callable

from hogvm.python.debugger import debugger, color_bytecode
from hogvm.python.objects import is_hog_error, new_hog_closure, CallFrame, ThrowFrame
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
MAX_FUNCTION_ARGS_LENGTH = 300


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
    upvalues: list[dict] = []
    mem_stack: list = []
    call_stack: list[CallFrame] = []
    throw_stack: list[ThrowFrame] = []
    declared_functions: dict[str, tuple[int, int]] = {}
    mem_used = 0
    max_mem_used = 0
    ops = 0
    stdout: list[str] = []
    colored_bytecode = color_bytecode(bytecode) if debug else []
    if isinstance(timeout, int):
        timeout = timedelta(seconds=timeout)

    if len(call_stack) == 0:
        call_stack.append(
            CallFrame(
                ip=-1,
                stack_start=0,
                arg_len=0,
                closure=new_hog_closure(
                    {
                        "__hogCallable__": "main",
                        "argCount": 0,
                        "upvalueCount": 0,
                        "ip": 1,
                        "name": "",
                    }
                ),
            )
        )

    frame = call_stack[-1]

    def splice_stack_1(start: int):
        nonlocal stack, mem_stack, mem_used
        for upvalue in reversed(upvalues):
            if upvalue["location"] >= start:
                if not upvalue["closed"]:
                    upvalue["closed"] = True
                    upvalue["value"] = stack[upvalue["location"]]
            else:
                break
        stack = stack[0:start]
        mem_used -= sum(mem_stack[start:])
        mem_stack = mem_stack[0:start]

    def next_token():
        nonlocal frame
        if frame.ip >= last_op:
            raise HogVMException("Unexpected end of bytecode")
        frame.ip += 1
        return bytecode[frame.ip]

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

    def capture_upvalue(index):
        nonlocal upvalues
        for upvalue in reversed(upvalues):
            if upvalue["location"] < index:
                break
            if upvalue["location"] == index:
                return upvalue
        created_upvalue = {"__hogUpValue__": True, "location": index, "closed": False, "value": None}
        upvalues.append(created_upvalue)
        upvalues.sort(key=lambda x: x["location"])
        return created_upvalue

    symbol: Any = None
    while frame.ip <= last_op:
        ops += 1
        symbol = bytecode[frame.ip]
        if (ops & 127) == 0:  # every 128th operation
            check_timeout()
        elif debug:
            debugger(symbol, bytecode, colored_bytecode, frame.ip, stack, call_stack, throw_stack)
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
                if globals and chain[0] in globals:
                    push_stack(deepcopy(get_nested_value(globals, chain)))
                elif functions and chain[0] in functions:
                    push_stack(
                        new_hog_closure(
                            {
                                "__hogCallable__": "stl",
                                "argCount": 0,
                                "upvalueCount": 0,
                                "ip": -1,
                                "name": chain[0],
                            }
                        )
                    )
                elif chain[0] in STL and len(chain) == 1:
                    push_stack(
                        new_hog_closure(
                            {
                                "__hogCallable__": "stl",
                                "argCount": STL[chain[0]].maxArgs,
                                "ip": -1,
                                "name": chain[0],
                            }
                        )
                    )
                else:
                    raise HogVMException(f"Global variable not found: {chain[0]}")
            case Operation.POP:
                pop_stack()
            case Operation.CLOSE_UPVALUE:
                splice_stack_1(len(stack) - 1)
            case Operation.RETURN:
                result = pop_stack()
                last_call_frame = call_stack.pop()
                if len(call_stack) == 0 or last_call_frame is None:
                    return BytecodeResult(result=result, stdout=stdout, bytecode=bytecode)
                stack_start = last_call_frame.stack_start
                splice_stack_1(stack_start)
                push_stack(result)
                frame = call_stack[-1]
                continue  # resume the loop without incrementing frame.ip

            case Operation.GET_LOCAL:
                stack_start = 0 if not call_stack else call_stack[-1].stack_start
                push_stack(stack[next_token() + stack_start])
            case Operation.SET_LOCAL:
                stack_start = 0 if not call_stack else call_stack[-1].stack_start
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
                frame.ip += count
            case Operation.JUMP_IF_FALSE:
                count = next_token()
                if not pop_stack():
                    frame.ip += count
            case Operation.JUMP_IF_STACK_NOT_NULL:
                count = next_token()
                if len(stack) > 0 and stack[-1] is not None:
                    frame.ip += count
            case Operation.DECLARE_FN:
                # DEPRECATED
                name = next_token()
                arg_len = next_token()
                body_len = next_token()
                declared_functions[name] = (frame.ip + 1, arg_len)
                frame.ip += body_len
            case Operation.CALLABLE:
                name = next_token()  # TODO: do we need it? it could change as the variable is reassigned
                arg_count = next_token()
                upvalue_count = next_token()
                body_length = next_token()
                push_stack(
                    {
                        "__hogCallable__": "local",
                        "argCount": arg_count,
                        "upvalueCount": upvalue_count,
                        "ip": frame.ip + 1,
                        "name": name,
                    }
                )
                frame.ip += body_length
            case Operation.CLOSURE:
                closure_callable = pop_stack()
                closure = new_hog_closure(closure_callable)
                stack_start = frame.stack_start
                upvalue_count = next_token()
                if upvalue_count != closure_callable["upvalueCount"]:
                    raise HogVMException(
                        f"Invalid upvalue count. Expected {closure_callable['upvalueCount']}, got {upvalue_count}"
                    )
                for _ in range(closure_callable["upvalueCount"]):
                    is_local, index = next_token(), next_token()
                    if is_local:
                        closure["upvalues"].append(capture_upvalue(stack_start + index))
                    else:
                        closure["upvalues"].append(frame.closure["upvalues"][index])
                push_stack(closure)
            case Operation.GET_UPVALUE:
                index = next_token()
                closure = frame.closure
                if index >= len(closure["upvalues"]):
                    raise HogVMException(f"Invalid upvalue index: {index}")
                upvalue = closure["upvalues"][index]
                if not isinstance(upvalue, dict) or upvalue.get("__hogUpValue__") is None:
                    raise HogVMException(f"Invalid upvalue: {upvalue}")
                if upvalue["closed"]:
                    push_stack(upvalue["value"])
                else:
                    push_stack(stack[upvalue["location"]])
            case Operation.SET_UPVALUE:
                index = next_token()
                closure = frame.closure
                if index >= len(closure["upvalues"]):
                    raise HogVMException(f"Invalid upvalue index: {index}")
                upvalue = closure["upvalues"][index]
                if not isinstance(upvalue, dict) or upvalue.get("__hogUpValue__") is None:
                    raise HogVMException(f"Invalid upvalue: {upvalue}")
                if upvalue["closed"]:
                    upvalue["value"] = pop_stack()
                else:
                    stack[upvalue["location"]] = pop_stack()
            case Operation.CALL_GLOBAL:
                check_timeout()
                name = next_token()
                if name in declared_functions:
                    # This is for backwards compatibility. We use a closure on the stack with local functions now.
                    func_ip, arg_len = declared_functions[name]
                    frame.ip += 1  # advance for when we return
                    frame = CallFrame(
                        ip=func_ip,
                        stack_start=len(stack) - arg_len,
                        arg_len=arg_len,
                        closure=new_hog_closure(
                            {
                                "__hogCallable__": "stl",
                                "argCount": arg_len,
                                "upvalueCount": 0,
                                "ip": -1,
                                "name": name,
                            }
                        ),
                    )
                    call_stack.append(frame)
                    continue  # resume the loop without incrementing frame.ip
                else:
                    # Shortcut for calling STL functions (can also be done with an STL function closure)
                    args = [pop_stack() for _ in range(next_token())]
                    if functions is not None and name in functions:
                        push_stack(functions[name](*args))
                    elif name in STL:
                        push_stack(STL[name].fn(args, team, stdout, timeout.total_seconds()))
                    else:
                        raise HogVMException(f"Unsupported function call: {name}")
            case Operation.CALL_LOCAL:
                check_timeout()
                closure = pop_stack()
                if not isinstance(closure, dict) or closure.get("__hogClosure__") is None:
                    raise HogVMException(f"Invalid closure: {closure}")
                callable = closure.get("callable")
                if not isinstance(callable, dict) or callable.get("__hogCallable__") is None:
                    raise HogVMException(f"Invalid callable: {callable}")
                args_length = next_token()
                if args_length > MAX_FUNCTION_ARGS_LENGTH:
                    raise HogVMException("Too many arguments")

                if callable.get("__hogCallable__") == "local":
                    if callable["argCount"] > args_length:
                        # TODO: specify minimum required arguments somehow
                        for _ in range(callable["argCount"] - args_length):
                            push_stack(None)
                    elif callable["argCount"] < args_length:
                        raise HogVMException(
                            f"Too many arguments. Passed {args_length}, expected {callable['argCount']}"
                        )
                    frame.ip += 1  # advance for when we return
                    frame = CallFrame(
                        ip=callable["ip"],
                        stack_start=len(stack) - callable["argCount"],
                        arg_len=callable["argCount"],
                        closure=closure,
                    )
                    call_stack.append(frame)
                    continue  # resume the loop without incrementing frame.ip

                elif callable.get("__hogCallable__") == "stl":
                    if callable["name"] not in STL:
                        raise HogVMException(f"Unsupported function call: {callable['name']}")
                    stl_fn = STL[callable["name"]]
                    if stl_fn.minArgs is not None and args_length < stl_fn.minArgs:
                        raise HogVMException(
                            f"Function {callable['name']} requires at least {stl_fn.minArgs} arguments"
                        )
                    if stl_fn.maxArgs is not None and args_length > stl_fn.maxArgs:
                        raise HogVMException(f"Function {callable['name']} requires at most {stl_fn.maxArgs} arguments")
                    args = [pop_stack() for _ in range(args_length)]
                    if stl_fn.maxArgs is not None and len(args) < stl_fn.maxArgs:
                        args += [None] * (stl_fn.maxArgs - len(args))
                    push_stack(stl_fn.fn(args, team, stdout, timeout.total_seconds()))

                elif callable.get("__hogCallable__") == "async":
                    raise HogVMException("Async functions are not supported")

                else:
                    raise HogVMException("Invalid callable")

            case Operation.TRY:
                throw_stack.append(
                    ThrowFrame(
                        call_stack_len=len(call_stack), stack_len=len(stack), catch_ip=frame.ip + 1 + next_token()
                    )
                )
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
                    last_throw = throw_stack.pop()
                    call_stack_len, stack_len, catch_ip = (
                        last_throw.call_stack_len,
                        last_throw.stack_len,
                        last_throw.catch_ip,
                    )
                    splice_stack_1(stack_len)
                    call_stack = call_stack[0:call_stack_len]
                    push_stack(exception)
                    frame = call_stack[-1]
                    frame.ip = catch_ip
                    continue
                else:
                    raise UncaughtHogVMException(
                        type=exception.get("type"),
                        message=exception.get("message"),
                        payload=exception.get("payload"),
                    )

        frame.ip += 1
    if debug:
        debugger(symbol, bytecode, colored_bytecode, frame.ip, stack, call_stack, throw_stack)
    if len(stack) > 1:
        raise HogVMException("Invalid bytecode. More than one value left on stack")
    if len(stack) == 1:
        result = pop_stack()
    return BytecodeResult(result=result, stdout=stdout, bytecode=bytecode)
