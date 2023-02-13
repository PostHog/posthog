from posthog.hogql import ast


class Visitor(object):
    def visit(self, node: ast.AST):
        return node.accept(self)


class EverythingVisitor(Visitor):
    def visit_expr(self, node: ast.Expr):
        raise ValueError("Can not visit generic Expr node")

    def visit_alias(self, node: ast.Alias):
        return ast.Alias(
            alias=node.alias,
            expr=self.visit(node.expr),
        )

    def visit_binary_operation(self, node: ast.BinaryOperation):
        return ast.BinaryOperation(
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_and(self, node: ast.And):
        return ast.And(exprs=[self.visit(expr) for expr in node.exprs])

    def visit_or(self, node: ast.Or):
        return ast.Or(exprs=[self.visit(expr) for expr in node.exprs])

    def visit_compare_operation(self, node: ast.CompareOperation):
        return ast.CompareOperation(
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_not(self, node: ast.Not):
        return ast.Not(expr=self.visit(node.expr))

    def visit_order_expr(self, node: ast.OrderExpr):
        return ast.OrderExpr(
            expr=self.visit(node.expr),
            order=node.order,
        )

    def visit_constant(self, node: ast.Constant):
        return node

    def visit_field(self, node: ast.Field):
        return node

    def visit_placeholder(self, node: ast.Placeholder):
        return node

    def visit_call(self, call: ast.Call):
        return ast.Call(
            name=call.name,
            args=[self.visit(arg) for arg in call.args],
        )
