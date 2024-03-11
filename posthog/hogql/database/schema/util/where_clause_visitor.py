from typing import TypeVar, Generic

from posthog.hogql import ast

from abc import ABC

T = TypeVar('T')



class HogQLASTVisitor(Generic[T], ABC):
    def visit(self, node: ast.Expr) -> T:
        if isinstance(node, ast.And):
            return self.visit_and(node)
        elif isinstance(node, ast.Or):
            return self.visit_or(node)
        elif isinstance(node, ast.Not):
            return self.visit_not(node)
        elif isinstance(node, ast.Call):
            return self.visit_call(node)
        elif isinstance(node, ast.Field):
            return self.visit_field(node)
        elif isinstance(node, ast.Constant):
            return self.visit_constant(node)
        elif isinstance(node, ast.CompareOperation):
            return self.visit_compare_operation(node)
        elif isinstance(node, ast.ArithmeticOperation):
            return self.visit_arithmetric_operation(node)
        elif isinstance(node, ast.Placeholder):
            return self.visit_placeholder(node)
        else:
            raise Exception(f"Unknown node type {type(node)}")

    def visit_and(self, node: ast.And) -> T:
        raise NotImplementedError()

    def visit_or(self, node: ast.Or) -> T:
        raise NotImplementedError()

    def visit_not(self, node: ast.Not) -> ast.Expr:
        raise NotImplementedError()

    def visit_call(self, node: ast.Call) -> ast.Expr:
        raise NotImplementedError()

    def visit_field(self, node: ast.Field) -> ast.Expr:
        raise NotImplementedError()

    def visit_constant(self, node: ast.Constant) -> ast.Expr:
        raise NotImplementedError()

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        raise NotImplementedError()

    def visit_arithmetric_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        raise NotImplementedError()

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        raise NotImplementedError()


class PassThroughHogQLASTVisitor(HogQLASTVisitor[ast.Expr]):
    def visit_and(self, node: ast.And) -> ast.Expr:
        return ast.And(exprs=[self.visit(node) for node in node.exprs])

    def visit_or(self, node: ast.Or) -> ast.Expr:
        return ast.Or(exprs=[self.visit(node) for node in node.exprs])

    def visit_not(self, node: ast.Not) -> ast.Expr:
        return ast.Not(expr=self.visit(node.expr))

    def visit_call(self, node: ast.Call) -> ast.Expr:
        return ast.Call(name=node.name, args=[self.visit(arg) for arg in node.args])

    def visit_field(self, node: ast.Field) -> ast.Expr:
        return ast.Field(chain=node.chain)

    def visit_constant(self, node: ast.Constant) -> ast.Expr:
        return ast.Constant(value=node.value)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        return ast.CompareOperation(
            op=node.op,
            left=self.visit(node.left),
            right=self.visit(node.right),
        )

    def visit_arithmetric_operation(self, node: ast.ArithmeticOperation) -> ast.Expr:
        return ast.ArithmeticOperation(
            op=node.op,
            left=self.visit(node.left),
            right=self.visit(node.right),
        )

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        return ast.Placeholder(field=node.field)

