from posthog.hogql import ast


class Visitor(object):
    def visit(self, node: ast.AST):
        return node.accept(self)


class EverythingVisitor(Visitor):
    def visit_expr(self, expr: ast.Expr):
        self.visit(expr)

    def visit_alias(self, alias: ast.Alias):
        self.visit(alias.expr)

    def visit_binary_operation(self, binary_operation: ast.BinaryOperation):
        self.visit(binary_operation.left)
        self.visit(binary_operation.right)

    def visit_and(self, and_: ast.And):
        for expr in and_.exprs:
            self.visit(expr)

    def visit_or(self, or_: ast.Or):
        for expr in or_.exprs:
            self.visit(expr)

    def visit_compare_operation(self, compare_operation: ast.CompareOperation):
        self.visit(compare_operation.left)
        self.visit(compare_operation.right)

    def visit_not(self, not_: ast.Not):
        self.visit(not_.expr)

    def visit_order_expr(self, order_expr: ast.OrderExpr):
        self.visit(order_expr.expr)

    def visit_constant(self, constant: ast.Constant):
        pass

    def visit_field(self, field: ast.Field):
        pass

    def visit_placeholder(self, placeholder: ast.Placeholder):
        pass

    def visit_call(self, call: ast.Call):
        for expr in call.args:
            self.visit(expr)
