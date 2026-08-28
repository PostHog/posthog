from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


class TrinoNormalizer(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node.prewhere is not None:
            node.where = ast.And(exprs=[node.prewhere, node.where]) if node.where is not None else node.prewhere
            node.prewhere = None
        super().visit_select_query(node)


def normalize_trino_ast(node: ast.AST) -> None:
    TrinoNormalizer().visit(node)
