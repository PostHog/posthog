from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


class JoinSources:
    """The `JoinExpr` of the input tree that each resolved `JoinExpr` came from, and the joins that the resolver
    added itself."""

    def __init__(self) -> None:
        # Each entry keeps its key node alive, so no other node can take its id.
        self._sources: dict[int, tuple[ast.JoinExpr, ast.JoinExpr]] = {}
        self._added: dict[int, ast.JoinExpr] = {}

    def record(self, node: ast.JoinExpr, source: ast.JoinExpr) -> None:
        """Records that `node`, a resolved join or a copy that the resolver made, came from `source`."""
        self._sources[id(node)] = (node, self.source_of(source) or source)

    def record_copied_tree(self, copy: ast.AST, source: ast.AST) -> None:
        """Records that each join in `copy`, a copy of `source`, came from the join at the same place in `source`."""
        for copied, original in zip(_all_joins(copy), _all_joins(source), strict=True):
            self.record(copied, original)

    def record_added(self, tree: ast.AST) -> None:
        """Records that the resolver added each join in `tree`, such as one in a saved view's body."""
        for join in _all_joins(tree):
            self._added[id(join)] = join

    def source_of(self, node: ast.JoinExpr) -> ast.JoinExpr | None:
        entry = self._sources.get(id(node))
        return entry[1] if entry is not None else None

    def is_added(self, node: ast.JoinExpr) -> bool:
        """Whether the resolver added the join that `node` came from."""
        source = self.source_of(node)
        return source is not None and id(source) in self._added


def _all_joins(tree: ast.AST) -> list[ast.JoinExpr]:
    collector = _JoinExprCollector()
    collector.visit(tree)
    return collector.joins


class _JoinExprCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.joins: list[ast.JoinExpr] = []

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        self.joins.append(node)
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        # The inherited visit follows the field's type. A field holds no join.
        pass
