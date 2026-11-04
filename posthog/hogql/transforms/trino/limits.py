from posthog.hogql import ast
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import TraversingVisitor

MAX_TRINO_SQL_LENGTH = 1_000_000
# Saved views are inlined before lowering, so ordinary models over a few views need tens of thousands of nodes.
MAX_TRINO_AST_NODES = 50_000


class TrinoCompilationBudget(TraversingVisitor):
    def __init__(self) -> None:
        self.remaining_nodes = MAX_TRINO_AST_NODES

    def consume_node(self, node: ast.AST | None) -> None:
        if node is None:
            return
        self.remaining_nodes -= 1
        if self.remaining_nodes < 0:
            raise TrinoLoweringError(
                "TRINO_AST_EXPANSION_LIMIT",
                "expressions that expand beyond the compilation limit; simplify the query",
                node if isinstance(node, ast.Expr) else None,
            )

    def visit(self, node: ast.AST | None) -> None:
        # Type nodes share one resolved graph, so counting them charges each field reference for its whole scope.
        if isinstance(node, ast.Type):
            return
        self.consume_node(node)
        super().visit(node)
