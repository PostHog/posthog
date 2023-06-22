from typing import List, Any

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor
from posthog.hogql.bytecode.operation import Operation


def create_bytecode(expr: ast.Expr) -> List[Any]:
    return BytecodeBuilder().visit(expr)


class BytecodeBuilder(CloningVisitor):
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
        return [Operation.FIELD, len(node.chain), *node.chain]

    def visit_constant(self, node: ast.Constant):
        return [Operation.CONSTANT, node.value]

    def visit_call(self, node: ast.Call):
        response = []
        for expr in node.args:
            response.extend(self.visit(expr))
        response.extend([Operation.CALL, node.name, len(node.args)])
        return response
