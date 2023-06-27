import re
from typing import List, Any, Dict

from posthog.hogql.bytecode.operation import Operation, HOGQL_BYTECODE_IDENTIFIER
from posthog.hogql.errors import HogQLException


def like(string, pattern, flags=0):
    pattern = re.escape(pattern).replace("%", ".*")
    re_pattern = re.compile(pattern, flags)
    return re_pattern.search(string) is not None


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
    if next(iterator) != HOGQL_BYTECODE_IDENTIFIER:
        raise HogQLException(f"Invalid bytecode. Must start with '{HOGQL_BYTECODE_IDENTIFIER}'")

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
            case Operation.FIELD:
                chain = [stack.pop() for _ in range(next(iterator))]
                stack.append(get_nested_value(fields, chain))
            case Operation.CALL:
                name = next(iterator)
                args = [stack.pop() for _ in range(next(iterator))]
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
                else:
                    raise HogQLException(f"Unsupported function call: {name}")
            case _:
                raise HogQLException(f"Unexpected node while running bytecode: {symbol}")
    return stack.pop()
