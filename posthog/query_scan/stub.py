"""Replace every subquery used as a value with a constant before asking ClickHouse for the plan.

``EXPLAIN`` runs a subquery to completion before it plans whenever the subquery stands in for a
value: the right side of ``x IN (subquery)``, or a scalar ``(SELECT ...)`` in a select list, a
comparison, a function argument, or a column ``WITH`` alias. Each such run reads real data. The
constant keeps the outer query's shape, so the plan still shows how it reads the events table.

A subquery that is a query source is kept, because the plan needs it: the root query, a ``FROM`` or
``JOIN`` table, a ``UNION`` member, and a subquery ``WITH`` body (``WITH a AS (SELECT ...)``). The
value subqueries taken out of the tree are collected so each can be explained on its own.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

from posthog.dataclasses import frozen


def _always_true() -> ast.Constant:
    return ast.Constant(value=1, type=ast.IntegerType(nullable=False))


def _stubbed_value() -> ast.Constant:
    # A value never decides which granules the outer read plans, so any constant stands in. NULL is
    # accepted wherever a stand-in can land (``toStartOfDay(NULL)``, ``concat('a', NULL)``), and
    # the ClickHouse printer inlines a ``None`` constant as ``NULL`` without a type.
    return ast.Constant(value=None)


@frozen
class StubResult:
    """The stubbed tree and the subqueries taken out of it, in the order they were visited."""

    stubbed: ast.Expr
    subqueries: tuple[ast.SelectQuery | ast.SelectSetQuery, ...]


def stub_in_subqueries(node: ast.Expr) -> StubResult:
    visitor = _StubVisitor()
    visitor.mark_source(node)
    stubbed = visitor.visit(node)
    return StubResult(stubbed=stubbed, subqueries=tuple(visitor.subqueries))


class _StubVisitor(CloningVisitor):
    def __init__(self) -> None:
        # The stubbed tree is printed as ClickHouse SQL, and the printer refuses a FROM clause
        # whose types were cleared, so the clone keeps the resolved types.
        super().__init__(clear_types=False)
        self.subqueries: list[ast.SelectQuery | ast.SelectSetQuery] = []
        # ``id()`` of each subquery that is a query source. A parent marks its source children before
        # ``super()`` recurses into them.
        self._source_ids: set[int] = set()

    def mark_source(self, node: ast.Expr) -> None:
        self._source_ids.add(id(node))

    def visit_select_query(self, node: ast.SelectQuery) -> ast.Expr:
        if id(node) not in self._source_ids:
            self.subqueries.append(node)
            return _stubbed_value()
        return super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.Expr:
        if id(node) not in self._source_ids:
            self.subqueries.append(node)
            return _stubbed_value()
        self.mark_source(node.initial_select_query)
        for member in node.subsequent_select_queries:
            self.mark_source(member.select_query)
        return super().visit_select_set_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        # ``super()`` passes this same table node to ``self.visit``, so marking it here is enough.
        if isinstance(node.table, (ast.SelectQuery, ast.SelectSetQuery)):
            self.mark_source(node.table)
        return super().visit_join_expr(node)

    def visit_cte(self, node: ast.CTE) -> ast.CTE:
        # A column CTE (``WITH (SELECT ...) AS a``) is a value, so it falls through to the value stub.
        if node.cte_type == "subquery" and isinstance(node.expr, (ast.SelectQuery, ast.SelectSetQuery)):
            self.mark_source(node.expr)
        return super().visit_cte(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        # A stub value left inside a comparison (``timestamp >= NULL``) would change which granules
        # the key condition plans, so the whole comparison folds to true, whatever the operator.
        before = len(self.subqueries)
        cloned = super().visit_compare_operation(node)
        if len(self.subqueries) > before:
            return _always_true()
        return cloned

    def visit_not(self, node: ast.Not) -> ast.Expr:
        # Fold the whole ``NOT``: stubbing only the inner comparison leaves ``NOT 1``, which the key
        # condition reads as always false, so the plan would report zero granules.
        before = len(self.subqueries)
        cloned = super().visit_not(node)
        if len(self.subqueries) > before:
            return _always_true()
        return cloned

    def visit_call(self, node: ast.Call) -> ast.Expr:
        # The parser emits ``NOT (...)`` as a ``not(...)`` call rather than an ``ast.Not``. Fold it
        # whole for the same reason as ``visit_not``.
        if node.name.lower() == "not" and len(node.args) == 1:
            before = len(self.subqueries)
            cloned = super().visit_call(node)
            if len(self.subqueries) > before:
                return _always_true()
            return cloned
        return super().visit_call(node)
