from typing import List, Any

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor
from posthog.hogql.bytecode.operation import Operation


def create_bytecode(expr: ast.Expr) -> List[Any]:
    return BytecodeBuilder().visit(expr)


class BytecodeBuilder(CloningVisitor):
    def visit_and(self, node: ast.And):
        response = [Operation.AND, len(node.exprs)]
        for expr in node.exprs:
            response.extend(self.visit(expr))
        return response

    def visit_or(self, node: ast.Or):
        response = [Operation.OR, len(node.exprs)]
        for expr in node.exprs:
            response.extend(self.visit(expr))
        return response

    def visit_not(self, node: ast.Not):
        return [Operation.NOT, *self.visit(node.expr)]

    def visit_compare_operation(self, node: ast.CompareOperation):
        return [node.op, *self.visit(node.left), *self.visit(node.right)]

    def visit_binary_operation(self, node: ast.BinaryOperation):
        return [node.op, *self.visit(node.left), *self.visit(node.right)]

    def visit_field(self, node: ast.Field):
        return [Operation.FIELD, len(node.chain), *node.chain]

    def visit_constant(self, node: ast.Constant):
        return [Operation.CONSTANT, node.value]

    def visit_call(self, node: ast.Call):
        response = [Operation.CALL, node.name, len(node.args)]
        for expr in node.args:
            response.extend(self.visit(expr))
        return response
