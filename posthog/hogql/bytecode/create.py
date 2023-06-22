from typing import List, Any

from posthog.hogql import ast
from posthog.hogql.errors import NotImplementedException
from posthog.hogql.visitor import Visitor
from posthog.hogql.bytecode.operation import Operation, HOGQL_BYTECODE_IDENTIFIER


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
        return [*self.visit(node.right), *self.visit(node.left), node.op]

    def visit_binary_operation(self, node: ast.BinaryOperation):
        return [*self.visit(node.right), *self.visit(node.left), node.op]

    def visit_field(self, node: ast.Field):
        chain = []
        for element in reversed(node.chain):
            chain.extend([Operation.CONSTANT, element])
        return [*chain, Operation.FIELD, len(node.chain)]

    def visit_tuple_access(self, node: ast.TupleAccess):
        return [Operation.CONSTANT, node.index, Operation.FIELD, 1]

    def visit_array_access(self, node: ast.ArrayAccess):
        return [*self.visit(node.property), Operation.FIELD, 1]

    def visit_constant(self, node: ast.Constant):
        return [Operation.CONSTANT, node.value]

    def visit_call(self, node: ast.Call):
        response = []
        for expr in reversed(node.args):
            response.extend(self.visit(expr))
        response.extend([Operation.CALL, node.name, len(node.args)])
        return response
