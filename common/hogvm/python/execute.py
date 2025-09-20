import re
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional

from common.hogvm.python.debugger import color_bytecode, debugger
from common.hogvm.python.objects import (
    CallFrame,
    ThrowFrame,
    is_hog_error,
    is_hog_upvalue,
    new_hog_callable,
    new_hog_closure,
)
from common.hogvm.python.operation import HOGQL_BYTECODE_IDENTIFIER, HOGQL_BYTECODE_IDENTIFIER_V0, Operation
from common.hogvm.python.stl import STL
from common.hogvm.python.stl.bytecode import BYTECODE_STL
from common.hogvm.python.utils import (
    HogVMException,
    HogVMMemoryExceededException,
    HogVMRuntimeExceededException,
    UncaughtHogVMException,
    calculate_cost,
    get_nested_value,
    like,
    set_nested_value,
    unify_comparison_types,
)

if TYPE_CHECKING:
    from posthog.models import Team

MAX_MEMORY = 64 * 1024 * 1024  # 64 MB
MAX_FUNCTION_ARGS_LENGTH = 300
CALLSTACK_LENGTH = 1000


@dataclass
class BytecodeResult:
    result: Any
    bytecodes: dict[str, list[Any]]
    stdout: list[str]


def execute_bytecode(
    input: list[Any] | dict,
    globals: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Callable[..., Any]]] = None,
    timeout=timedelta(seconds=5),
    team: Optional["Team"] = None,
    debug=False,
) -> BytecodeResult:
    bytecodes = input if isinstance(input, dict) else {"root": {"bytecode": input}}
    root_bytecode = bytecodes.get("root", {}).get("bytecode", []) or []

    if (
        not root_bytecode
        or len(root_bytecode) == 0
        or (root_bytecode[0] != HOGQL_BYTECODE_IDENTIFIER and root_bytecode[0] != HOGQL_BYTECODE_IDENTIFIER_V0)
    ):
        raise HogVMException(f"Invalid bytecode. Must start with '{HOGQL_BYTECODE_IDENTIFIER}'")
    version = root_bytecode[1] if len(root_bytecode) >= 2 and root_bytecode[0] == HOGQL_BYTECODE_IDENTIFIER else 0
    start_time = time.time()
    last_op = len(root_bytecode) - 1
    stack: list = []
    upvalues: list[dict] = []
    upvalues_by_id: dict[int, dict] = {}
    mem_stack: list = []
    call_stack: list[CallFrame] = []
    throw_stack: list[ThrowFrame] = []
    declared_functions: dict[str, tuple[int, int]] = {}
    mem_used = 0
    max_mem_used = 0
    ops = 0
    stdout: list[str] = []
    debug_bytecode = []
    if isinstance(timeout, int):
        timeout = timedelta(seconds=timeout)

    if len(call_stack) == 0:
        call_stack.append(
            CallFrame(
                ip=0,
                chunk="root",
                stack_start=0,
                arg_len=0,
                closure=new_hog_closure(
                    new_hog_callable(
                        type="local",
                        arg_count=0,
                        upvalue_count=0,
                        ip=0,
                        chunk="root",
                        name="",
                    )
                ),
            )
        )
    frame = call_stack[-1]
    chunk_bytecode: list[Any] = root_bytecode
    chunk_globals = globals

    def set_chunk_bytecode():
        nonlocal chunk_bytecode, chunk_globals, last_op, debug_bytecode
        if not frame.chunk or frame.chunk == "root":
            chunk_bytecode = root_bytecode
            chunk_globals = globals
        elif frame.chunk.startswith("stl/") and frame.chunk[4:] in BYTECODE_STL:
            chunk_bytecode = BYTECODE_STL[frame.chunk[4:]][1]
            chunk_globals = {}
        elif bytecodes.get(frame.chunk):
            chunk_bytecode = bytecodes[frame.chunk].get("bytecode", [])
            chunk_globals = bytecodes[frame.chunk].get("globals", {})
        else:
            raise HogVMException(f"Unknown chunk: {frame.chunk}")
        last_op = len(chunk_bytecode) - 1
        if debug:
            debug_bytecode = color_bytecode(chunk_bytecode)
        if frame.ip == 0 and (chunk_bytecode[0] == "_H" or chunk_bytecode[0] == "_h"):
            # TODO: store chunk version
            frame.ip += 2 if chunk_bytecode[0] == "_H" else 1

    set_chunk_bytecode()

    def stack_keep_first_elements(count: int) -> list[Any]:
        nonlocal stack, mem_stack, mem_used
        if count < 0 or len(stack) < count:
            raise HogVMException("Stack underflow")
        for upvalue in reversed(upvalues):
            if upvalue["location"] >= count:
                if not upvalue["closed"]:
                    upvalue["closed"] = True
                    upvalue["value"] = stack[upvalue["location"]]
            else:
                break
        removed = stack[count:]
        stack = stack[0:count]
        mem_used -= sum(mem_stack[count:])
        mem_stack = mem_stack[0:count]
        return removed

    def next_token():
        nonlocal frame, chunk_bytecode
        if frame.ip >= last_op:
            raise HogVMException("Unexpected end of bytecode")
        frame.ip += 1
        return chunk_bytecode[frame.ip]

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
            raise HogVMMemoryExceededException(memory_limit=MAX_MEMORY, attempted_memory=mem_used)

    def check_timeout():
        if time.time() - start_time > timeout.total_seconds() and not debug:
            raise HogVMRuntimeExceededException(timeout_seconds=timeout.total_seconds(), ops_performed=ops)

    def capture_upvalue(index) -> dict:
        nonlocal upvalues
        for upvalue in reversed(upvalues):
            if upvalue["location"] < index:
                break
            if upvalue["location"] == index:
                return upvalue
        created_upvalue = {
            "__hogUpValue__": True,
            "location": index,
            "closed": False,
            "value": None,
            "id": len(upvalues) + 1,
        }
        upvalues.append(created_upvalue)
        upvalues_by_id[created_upvalue["id"]] = created_upvalue
        upvalues.sort(key=lambda x: x["location"])
        return created_upvalue

    symbol: Any = None
    while True:
        # Return or jump back to the previous call frame if ran out of bytecode to execute in this one, and return null
        if frame.ip > last_op:
            last_call_frame = call_stack.pop()
            if len(call_stack) == 0 or last_call_frame is None:
                if len(stack) > 1:
                    raise HogVMException("Invalid bytecode. More than one value left on stack")
                return BytecodeResult(
                    result=pop_stack() if len(stack) > 0 else None, stdout=stdout, bytecodes=bytecodes
                )
            stack_start = last_call_frame.stack_start
            stack_keep_first_elements(stack_start)
            push_stack(None)
            frame = call_stack[-1]
            set_chunk_bytecode()

        ops += 1
        symbol = chunk_bytecode[frame.ip]
        if (ops & 127) == 0:  # every 128th operation
            check_timeout()
        elif debug:
            debugger(symbol, chunk_bytecode, debug_bytecode, frame.ip, stack, call_stack, throw_stack)
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
                var1, var2 = unify_comparison_types(pop_stack(), pop_stack())
                push_stack(var1 == var2)
            case Operation.NOT_EQ:
                var1, var2 = unify_comparison_types(pop_stack(), pop_stack())
                push_stack(var1 != var2)
            case Operation.GT:
                var1, var2 = unify_comparison_types(pop_stack(), pop_stack())
                push_stack(var1 > var2)
            case Operation.GT_EQ:
                var1, var2 = unify_comparison_types(pop_stack(), pop_stack())
                push_stack(var1 >= var2)
            case Operation.LT:
                var1, var2 = unify_comparison_types(pop_stack(), pop_stack())
                push_stack(var1 < var2)
            case Operation.LT_EQ:
                var1, var2 = unify_comparison_types(pop_stack(), pop_stack())
                push_stack(var1 <= var2)
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
                push_stack(bool(re.search(re.compile(args[1]), args[0])) if args[0] and args[1] else False)
            case Operation.NOT_REGEX:
                args = [pop_stack(), pop_stack()]
                # TODO: swap this for re2, as used in HogQL/ClickHouse and in the NodeJS VM
                push_stack(not bool(re.search(re.compile(args[1]), args[0])) if args[0] and args[1] else False)
            case Operation.IREGEX:
                args = [pop_stack(), pop_stack()]
                push_stack(
                    bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0]))
                    if args[0] and args[1]
                    else False
                )
            case Operation.NOT_IREGEX:
                args = [pop_stack(), pop_stack()]
                push_stack(
                    not bool(re.search(re.compile(args[1], re.RegexFlag.IGNORECASE), args[0]))
                    if args[0] and args[1]
                    else False
                )
            case Operation.GET_GLOBAL:
                chain = [pop_stack() for _ in range(next_token())]
                if chunk_globals and chain[0] in chunk_globals:
                    push_stack(deepcopy(get_nested_value(chunk_globals, chain, True)))
                elif functions and chain[0] in functions:
                    push_stack(
                        new_hog_closure(
                            new_hog_callable(
                                type="stl",
                                name=chain[0],
                                arg_count=0,
                                upvalue_count=0,
                                ip=-1,
                                chunk="stl",
                            )
                        )
                    )
                elif chain[0] in STL and len(chain) == 1:
                    push_stack(
                        new_hog_closure(
                            new_hog_callable(
                                type="stl",
                                name=chain[0],
                                arg_count=STL[chain[0]].maxArgs or 0,
                                upvalue_count=0,
                                ip=-1,
                                chunk="stl",
                            )
                        )
                    )
                elif chain[0] in BYTECODE_STL and len(chain) == 1:
                    push_stack(
                        new_hog_closure(
                            new_hog_callable(
                                type="stl",
                                name=chain[0],
                                arg_count=len(BYTECODE_STL[chain[0]][0]),
                                upvalue_count=0,
                                ip=0,
                                chunk=f"stl/{chain[0]}",
                            )
                        )
                    )
                else:
                    raise HogVMException(f"Global variable not found: {chain[0]}")
            case Operation.POP:
                pop_stack()
            case Operation.CLOSE_UPVALUE:
                stack_keep_first_elements(len(stack) - 1)
            case Operation.RETURN:
                response = pop_stack()
                last_call_frame = call_stack.pop()
                if len(call_stack) == 0 or last_call_frame is None:
                    return BytecodeResult(result=response, stdout=stdout, bytecodes=bytecodes)
                stack_start = last_call_frame.stack_start
                stack_keep_first_elements(stack_start)
                push_stack(response)
                frame = call_stack[-1]
                set_chunk_bytecode()
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
                    new_hog_callable(
                        type="local",
                        name=name,
                        chunk=frame.chunk,
                        arg_count=arg_count,
                        upvalue_count=upvalue_count,
                        ip=frame.ip + 1,
                    )
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
                        closure["upvalues"].append(capture_upvalue(stack_start + index)["id"])
                    else:
                        closure["upvalues"].append(frame.closure["upvalues"][index])
                push_stack(closure)
            case Operation.GET_UPVALUE:
                index = next_token()
                closure = frame.closure
                if index >= len(closure["upvalues"]):
                    raise HogVMException(f"Invalid upvalue index: {index}")
                upvalue = upvalues_by_id[closure["upvalues"][index]]
                if not is_hog_upvalue(upvalue):
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
                upvalue = upvalues_by_id[closure["upvalues"][index]]
                if not is_hog_upvalue(upvalue):
                    raise HogVMException(f"Invalid upvalue: {upvalue}")
                if upvalue["closed"]:
                    upvalue["value"] = pop_stack()
                else:
                    stack[upvalue["location"]] = pop_stack()
            case Operation.CALL_GLOBAL:
                check_timeout()
                name = next_token()
                arg_count = next_token()
                # This is for backwards compatibility. We use a closure on the stack with local functions now.
                if name in declared_functions:
                    func_ip, arg_len = declared_functions[name]
                    frame.ip += 1  # advance for when we return
                    if arg_len > arg_count:
                        for _ in range(arg_len - arg_count):
                            push_stack(None)
                    frame = CallFrame(
                        ip=func_ip,
                        chunk=frame.chunk,
                        stack_start=len(stack) - arg_len,
                        arg_len=arg_len,
                        closure=new_hog_closure(
                            new_hog_callable(
                                type="local",
                                name=name,
                                arg_count=arg_len,
                                upvalue_count=0,
                                ip=func_ip,
                                chunk=frame.chunk,
                            )
                        ),
                    )
                    set_chunk_bytecode()
                    call_stack.append(frame)
                    continue  # resume the loop without incrementing frame.ip
                else:
                    if name == "import":
                        if arg_count != 1:
                            raise HogVMException("Function import requires exactly 1 argument")
                        module_name = pop_stack()
                        frame.ip += 1  # advance for when we return
                        frame = CallFrame(
                            ip=0,
                            chunk=module_name,
                            stack_start=len(stack),
                            arg_len=0,
                            closure=new_hog_closure(
                                new_hog_callable(
                                    type="local",
                                    name=module_name,
                                    arg_count=0,
                                    upvalue_count=0,
                                    ip=0,
                                    chunk=module_name,
                                )
                            ),
                        )
                        set_chunk_bytecode()
                        call_stack.append(frame)
                        continue
                    elif functions is not None and name in functions:
                        if version == 0:
                            args = [pop_stack() for _ in range(arg_count)]
                        else:
                            args = stack_keep_first_elements(len(stack) - arg_count)
                        push_stack(functions[name](*args))
                    elif name in STL:
                        if version == 0:
                            args = [pop_stack() for _ in range(arg_count)]
                        else:
                            args = stack_keep_first_elements(len(stack) - arg_count)
                        push_stack(STL[name].fn(args, team, stdout, timeout.total_seconds()))
                    elif name in BYTECODE_STL:
                        arg_names = BYTECODE_STL[name][0]
                        if len(arg_names) != arg_count:
                            raise HogVMException(f"Function {name} requires exactly {len(arg_names)} arguments")
                        frame.ip += 1  # advance for when we return
                        frame = CallFrame(
                            ip=0,
                            chunk=f"stl/{name}",
                            stack_start=len(stack) - arg_count,
                            arg_len=arg_count,
                            closure=new_hog_closure(
                                new_hog_callable(
                                    type="stl",
                                    name=name,
                                    arg_count=arg_count,
                                    upvalue_count=0,
                                    ip=0,
                                    chunk=f"stl/{name}",
                                )
                            ),
                        )
                        set_chunk_bytecode()
                        call_stack.append(frame)
                        continue  # resume the loop without incrementing frame.ip
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
                        chunk=callable["chunk"],
                        stack_start=len(stack) - callable["argCount"],
                        arg_len=callable["argCount"],
                        closure=closure,
                    )
                    set_chunk_bytecode()
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
                    if version == 0:
                        args = [pop_stack() for _ in range(args_length)]
                    else:
                        args = list(reversed([pop_stack() for _ in range(args_length)]))
                        if stl_fn.maxArgs is not None and len(args) < stl_fn.maxArgs:
                            args = [*args, *([None] * (stl_fn.maxArgs - len(args)))]
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
                    stack_keep_first_elements(stack_len)
                    call_stack = call_stack[0:call_stack_len]
                    push_stack(exception)
                    frame = call_stack[-1]
                    set_chunk_bytecode()
                    frame.ip = catch_ip
                    continue
                else:
                    raise UncaughtHogVMException(
                        type=exception.get("type"),
                        message=exception.get("message"),
                        payload=exception.get("payload"),
                    )
            case _:
                raise HogVMException(
                    f'Unexpected node while running bytecode in chunk "{frame.chunk}": {chunk_bytecode[frame.ip]}'
                )

        frame.ip += 1

    return BytecodeResult(result=pop_stack() if len(stack) > 0 else None, stdout=stdout, bytecodes=bytecodes)


def validate_bytecode(bytecode: list[Any] | dict, inputs: Optional[dict] = None) -> tuple[bool, Optional[str]]:
    try:
        event = {
            "uuid": "test-event-id",
            "event": "test-event",
            "distinct_id": "test-distinct-id",
            "properties": {},
            "timestamp": "2024-01-01T00:00:00Z",
        }
        test_globals = {
            "event": event,
            "person": {"properties": {}},
            "inputs": inputs or {},
        }

        execute_bytecode(
            bytecode,
            globals=test_globals,
            timeout=timedelta(milliseconds=100),  # Short timeout for validation
            functions={
                "print": lambda *args: None,  # No-op print function
                "fetch": lambda *args: {"status": 200, "body": {}},  # Mock fetch
            },
        )
        return True, None

    except HogVMRuntimeExceededException as e:
        return (
            False,
            f"Your function is taking too long to run (over {e.timeout_seconds} seconds). Please simplify your code.",
        )
    except HogVMMemoryExceededException as e:
        memory_mb = e.memory_limit / (1024 * 1024)
        attempted_mb = e.attempted_memory / (1024 * 1024)
        return False, f"Your function needs too much memory ({attempted_mb:.1f}MB). The limit is {memory_mb:.1f}MB."
    except HogVMException as e:
        return False, f"Function execution error: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error during function validation: {str(e)}"
