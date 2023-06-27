from typing import List, Any

from posthog.hogql import ast
from posthog.hogql.errors import NotImplementedException
from posthog.hogql.visitor import Visitor
from hogvm.python.operation import Operation, HOGQL_BYTECODE_IDENTIFIER, SUPPORTED_FUNCTIONS

COMPARE_OPERATIONS = {
    ast.CompareOperationOp.Eq: Operation.EQ,
    ast.CompareOperationOp.NotEq: Operation.NOT_EQ,
    ast.CompareOperationOp.Gt: Operation.GT,
    ast.CompareOperationOp.GtEq: Operation.GT_EQ,
    ast.CompareOperationOp.Lt: Operation.LT,
    ast.CompareOperationOp.LtEq: Operation.LT_EQ,
    ast.CompareOperationOp.Like: Operation.LIKE,
    ast.CompareOperationOp.ILike: Operation.ILIKE,
    ast.CompareOperationOp.NotLike: Operation.NOT_LIKE,
    ast.CompareOperationOp.NotILike: Operation.NOT_ILIKE,
    ast.CompareOperationOp.In: Operation.IN,
    ast.CompareOperationOp.NotIn: Operation.NOT_IN,
    ast.CompareOperationOp.Regex: Operation.REGEX,
    ast.CompareOperationOp.NotRegex: Operation.NOT_REGEX,
}

BINARY_OPERATIONS = {
    ast.BinaryOperationOp.Add: Operation.PLUS,
    ast.BinaryOperationOp.Sub: Operation.MINUS,
    ast.BinaryOperationOp.Mult: Operation.MULTIPLY,
    ast.BinaryOperationOp.Div: Operation.DIVIDE,
    ast.BinaryOperationOp.Mod: Operation.MOD,
}


def to_bytecode(expr: str) -> List[any]:
    from posthog.hogql.parser import parse_expr

    return create_bytecode(parse_expr(expr))


def create_bytecode(expr: ast.Expr) -> List[Any]:
    try:
        bytecode = [HOGQL_BYTECODE_IDENTIFIER]
        bytecode.extend(BytecodeBuilder().visit(expr))
        return bytecode
    except NotImplementedException as e:
        raise NotImplementedException(f"Unsupported HogQL bytecode node: {str(e)}")


class BytecodeBuilder(Visitor):
    def visit_and(self, node: ast.And):
        response = []
        for expr in reversed(node.exprs):
            response.extend(self.visit(expr))
        response.append(Operation.AND)
        response.append(len(node.exprs))
        return response

    def visit_or(self, node: ast.Or):
        response = []
        for expr in reversed(node.exprs):
            response.extend(self.visit(expr))
        response.append(Operation.OR)
        response.append(len(node.exprs))
        return response

    def visit_not(self, node: ast.Not):
        return [*self.visit(node.expr), Operation.NOT]

    def visit_compare_operation(self, node: ast.CompareOperation):
        return [*self.visit(node.right), *self.visit(node.left), COMPARE_OPERATIONS[node.op]]

    def visit_binary_operation(self, node: ast.BinaryOperation):
        return [*self.visit(node.right), *self.visit(node.left), BINARY_OPERATIONS[node.op]]

    def visit_field(self, node: ast.Field):
        chain = []
        for element in reversed(node.chain):
            chain.extend([Operation.STRING, element])
        return [*chain, Operation.FIELD, len(node.chain)]

    def visit_tuple_access(self, node: ast.TupleAccess):
        return [Operation.INTEGER, node.index, Operation.FIELD, 1]

    def visit_array_access(self, node: ast.ArrayAccess):
        return [*self.visit(node.property), Operation.FIELD, 1]

    def visit_constant(self, node: ast.Constant):
        if node.value is True:
            return [Operation.TRUE]
        elif node.value is False:
            return [Operation.FALSE]
        elif node.value is None:
            return [Operation.NULL]
        elif isinstance(node.value, int):
            return [Operation.INTEGER, node.value]
        elif isinstance(node.value, float):
            return [Operation.FLOAT, node.value]
        elif isinstance(node.value, str):
            return [Operation.STRING, node.value]
        else:
            raise NotImplementedException(f"Unsupported constant type: {type(node.value)}")

    def visit_call(self, node: ast.Call):
        if node.name not in SUPPORTED_FUNCTIONS:
            raise NotImplementedException(f"Unsupported function: {node.name}")
        response = []
        for expr in reversed(node.args):
            response.extend(self.visit(expr))
        response.extend([Operation.CALL, node.name, len(node.args)])
        return response
