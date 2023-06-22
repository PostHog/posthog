import re
from typing import List, Any, Dict

from posthog.hogql.ast import BinaryOperationOp, CompareOperationOp
from posthog.hogql.bytecode.operation import Operation
from posthog.hogql.errors import HogQLException


def like(string, pattern, flags=0):
    pattern = re.escape(pattern).replace("%", ".*")
    re_pattern = re.compile(pattern, flags)
    return re_pattern.match(string) is not None


def get_nested_value(obj, chain) -> Any:
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


def execute_bytecode(bytecode: List[Any], fields: Dict[str, Any]) -> Any:
    stack = []
    iterator = iter(bytecode)

    while (symbol := next(iterator, None)) is not None:
        match symbol:
            case None:
                return stack.pop()
            case Operation.CONSTANT:
                stack.append(next(iterator))
            case Operation.NOT:
                stack.append(not stack.pop())
            case Operation.AND:
                stack.append(all([stack.pop() for _ in range(next(iterator))]))
            case Operation.OR:
                stack.append(any([stack.pop() for _ in range(next(iterator))]))
            case BinaryOperationOp.Add:
                stack.append(stack.pop() + stack.pop())
            case BinaryOperationOp.Sub:
                stack.append(stack.pop() - stack.pop())
            case BinaryOperationOp.Div:
                stack.append(stack.pop() / stack.pop())
            case BinaryOperationOp.Mult:
                stack.append(stack.pop() * stack.pop())
            case BinaryOperationOp.Mod:
                stack.append(stack.pop() % stack.pop())
            case CompareOperationOp.Eq:
                stack.append(stack.pop() == stack.pop())
            case CompareOperationOp.NotEq:
                stack.append(stack.pop() != stack.pop())
            case CompareOperationOp.Gt:
                stack.append(stack.pop() > stack.pop())
            case CompareOperationOp.GtE:
                stack.append(stack.pop() >= stack.pop())
            case CompareOperationOp.Lt:
                stack.append(stack.pop() < stack.pop())
            case CompareOperationOp.LtE:
                stack.append(stack.pop() <= stack.pop())
            case CompareOperationOp.Like:
                stack.append(like(stack.pop(), stack.pop()))
            case CompareOperationOp.ILike:
                stack.append(like(stack.pop(), stack.pop(), re.IGNORECASE))
            case CompareOperationOp.NotLike:
                stack.append(not like(stack.pop(), stack.pop()))
            case CompareOperationOp.NotILike:
                stack.append(not like(stack.pop(), stack.pop(), re.IGNORECASE))
            case CompareOperationOp.In:
                stack.append(stack.pop() in stack.pop())
            case CompareOperationOp.NotIn:
                stack.append(stack.pop() not in stack.pop())
            case Operation.FIELD:
                chain = [stack.pop() for _ in range(next(iterator))]
                stack.append(get_nested_value(fields, chain))
            case Operation.CALL:
                name = next(iterator)
                args = [stack.pop() for _ in range(next(iterator))]
                if name == "concat":
                    stack.append("".join([to_concat_arg(arg) for arg in args]))
                else:
                    raise HogQLException(f"Unsupported function call: {name}")
            case _:
                raise HogQLException(f"Unexpected node while running bytecode: {symbol}")
    return stack.pop()
