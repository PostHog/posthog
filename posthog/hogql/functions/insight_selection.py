from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


class InsightSelectionFinder(TraversingVisitor):
    def __init__(self, expr: ast.Expr):
        super().__init__()
        self.found = False
        self.visit(expr)

    def visit_call(self, node: ast.Call):
        if node.name == "matchesInsight":
            self.found = True
        else:
            super().visit_call(node)
