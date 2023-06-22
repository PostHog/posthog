from typing import List, Any, Dict

from posthog.hogql.ast import BinaryOperationOp
from posthog.hogql.bytecode.operation import Operation
from posthog.hogql.errors import HogQLException


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
                stack.append(stack.pop() and stack.pop())
            case Operation.OR:
                stack.append(stack.pop() or stack.pop())
            case BinaryOperationOp.Add:
                stack.append(stack.pop() + stack.pop())
            case Operation.MINUS:
                stack.append(stack.pop() - stack.pop())
            case Operation.DIVIDE:
                stack.append(stack.pop() / stack.pop())
            case Operation.MULTIPLY:
                stack.append(stack.pop() * stack.pop())
            case _:
                raise HogQLException("Unexpected node while running bytecode!")
    return stack.pop()
