"""Replace every ``x IN (subquery)`` with a constant before ClickHouse is asked for the plan.

``EXPLAIN`` runs each ``IN (subquery)`` to completion to build its set before it plans the outer
query. That reads real data, which defeats a plan-only analysis. Replacing the comparison with a
constant keeps the rest of the query's shape, so the plan still shows how the outer query reads the
events table. The replaced subqueries are collected so each can be explained on its own.
"""

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

from posthog.dataclasses import frozen

# The global and cohort variants appear only after the tree is lowered, so covering them lets the
# stub run on the lowered tree too. The subquery-right check keeps literal IN lists untouched.
_IN_SUBQUERY_OPS = frozenset(
    {
        ast.CompareOperationOp.In,
        ast.CompareOperationOp.NotIn,
        ast.CompareOperationOp.GlobalIn,
        ast.CompareOperationOp.GlobalNotIn,
        ast.CompareOperationOp.InCohort,
        ast.CompareOperationOp.NotInCohort,
    }
)


@frozen
class StubResult:
    """The stubbed tree and the subqueries taken out of it, in the order they were visited."""

    stubbed: ast.Expr
    subqueries: tuple[ast.SelectQuery | ast.SelectSetQuery, ...]


def stub_in_subqueries(node: ast.Expr) -> StubResult:
    visitor = _StubVisitor()
    stubbed = visitor.visit(node)
    return StubResult(stubbed=stubbed, subqueries=tuple(visitor.subqueries))


def _in_subquery_right(node: ast.Expr) -> ast.SelectQuery | ast.SelectSetQuery | None:
    if (
        isinstance(node, ast.CompareOperation)
        and node.op in _IN_SUBQUERY_OPS
        and isinstance(node.right, (ast.SelectQuery, ast.SelectSetQuery))
    ):
        return node.right
    return None


class _StubVisitor(CloningVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.subqueries: list[ast.SelectQuery | ast.SelectSetQuery] = []

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.Expr:
        right = _in_subquery_right(node)
        if right is not None:
            self.subqueries.append(right)
            return ast.Constant(value=1)
        return super().visit_compare_operation(node)

    def visit_not(self, node: ast.Not) -> ast.Expr:
        # Fold the whole ``NOT``: stubbing only the inner comparison leaves ``NOT 1``, which the key
        # condition reads as always false, so the plan would report zero granules.
        right = _in_subquery_right(node.expr)
        if right is not None:
            self.subqueries.append(right)
            return ast.Constant(value=1)
        return super().visit_not(node)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        # The parser emits ``NOT (...)`` as a ``not(...)`` call, not an ``ast.Not``, keeping the source
        # case, so the same fold applies here.
        if node.name.lower() == "not" and len(node.args) == 1:
            right = _in_subquery_right(node.args[0])
            if right is not None:
                self.subqueries.append(right)
                return ast.Constant(value=1)
        return super().visit_call(node)
