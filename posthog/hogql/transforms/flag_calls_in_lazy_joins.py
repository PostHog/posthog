import dataclasses
from collections.abc import Callable
from functools import partial

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoinToAdd
from posthog.hogql.database.schema.util.where_clause_extractor import event_field_type
from posthog.hogql.resolver_utils import get_long_table_name
from posthog.hogql.transforms.events_predicate_pushdown import PREDICATE_SAFE_JOIN_TYPES
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import (
    EventsScan,
    FlagCallScope,
    Resolve,
    SyntaxVisitor,
    and_conditions,
    compared_values,
    comparison_of,
    filter_conjuncts,
    flag_calls_only_in_flag_evaluations_error,
    is_flag_called,
    pins_flag_calls,
    swap_database,
    swap_flag_calls,
    swaps_flag_calls,
    team_flag_key_compares_as_string,
)
from posthog.hogql.visitor import clone_expr

# A filter added to the WHERE of a subquery that sets only these clauses keeps the rows it would keep after the
# subquery. Any other clause, including one SelectQuery gains later, refuses the pin.
_ROW_PRESERVING_CLAUSES = frozenset(
    {"start", "end", "type", "view_name", "select", "select_from", "where", "prewhere", "order_by"}
)


def read_flag_calls_in_lazy_join(
    join_to_add: ast.JoinExpr,
    join_scope: LazyJoinToAdd,
    node: ast.SelectQuery,
    original_select_type: ast.SelectQueryType,
    context: HogQLContext,
    resolve: Resolve[ast.SelectQuery],
) -> None:
    """Points the `events` scan in the subquery of `join_to_add` at `posthog.flag_evaluations` when `swap_flag_calls`
    accepts it, or raises when the organization's flag calls are only in `flag_evaluations` and the join would miss
    them. `node` is the SELECT that owns the join. It changes `join_to_add.table` in place.

    It acts only on a subquery that scans `events`, for an organization that reads flag calls from `flag_evaluations`.
    Without a pin from `node`, it runs `swap_flag_calls` only when `swaps_flag_calls` accepts the subquery.

    For an organization whose flag calls are only in `flag_evaluations`, a subquery that does not pin `event` to flag
    calls itself gets a pin on its own scan when all of these hold:

    - A top-level condition of the WHERE or PREWHERE of `node` pins the join's `event` to flag calls, so every row
      that `node` keeps has `event = '$feature_flag_called'` on the joined side. The condition is matched by the
      resolved type of `event`, not by its name.
    - The join type, without a `GLOBAL` prefix, is one of `PREDICATE_SAFE_JOIN_TYPES`. Each output row of those joins
      comes from one pair of rows, and the pin is false on the row a missing match produces. An ASOF or ANY join picks
      one row among several matches, so a filter before the join can pick a different row.
    - The subquery passes each row of its scan through on its own. A filter before a GROUP BY, an aggregate, a window
      function, a LIMIT or DISTINCT changes which rows come out.

    It raises when `node` compares the join's `event` with `$feature_flag_called` by `=` or `IN` and one of these
    does not hold. A `!=` or `NOT IN` under an odd number of NOTs counts as `=` or `IN`. The function builds the pin
    on the subquery's scan, so no name from `node` has to resolve in the subquery.
    """
    subquery = join_to_add.table
    if not isinstance(subquery, ast.SelectQuery):
        return
    database = swap_database(context)
    if database is None:
        return
    scan = EventsScan.of(subquery, partial(team_flag_key_compares_as_string, context), {}, database)
    if scan is None:
        return
    join_name = _join_name(join_scope)
    scope = FlagCallScope.join(join_name)
    pin: ast.Expr | None = None
    if context.flag_calls_only_in_flag_evaluations() and not scan.pins_flag_calls(
        filter_conjuncts(subquery), needs_flag_key=False
    ):
        reads_join_event = _join_event_reader(join_scope, original_select_type)
        if not pins_flag_calls(filter_conjuncts(node), reads_join_event, None):
            if not _compares_with_flag_calls(node, reads_join_event):
                return
            raise flag_calls_only_in_flag_evaluations_error(
                f"it compares {join_name}.event with {FLAG_CALLED_EVENT}, but the query's WHERE doesn't keep only those events",
                scope,
            )
        if (join_to_add.join_type or "").removeprefix("GLOBAL ") not in PREDICATE_SAFE_JOIN_TYPES:
            raise flag_calls_only_in_flag_evaluations_error(
                f"its join type, {join_to_add.join_type}, can't apply a filter on {join_name}.event before the join",
                scope,
            )
        if not _passes_rows_through(subquery):
            raise flag_calls_only_in_flag_evaluations_error(
                f"the subquery of {join_name} groups, limits, aggregates or windows its rows, so it can't take a "
                "filter on event before the join",
                scope,
            )
        pin = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[scan.alias, "event"]),
            right=ast.Constant(value=FLAG_CALLED_EVENT),
        )
    elif not swaps_flag_calls(subquery, context):
        return
    # A join resolver can copy resolved nodes from `node` into the subquery. The swap resolves the subquery again.
    subquery = clone_expr(subquery, clear_types=True, clear_locations=True)
    subquery.where = and_conditions([subquery.where, pin])
    join_to_add.table = swap_flag_calls(subquery, context, resolve, scope=scope).source


def refuse_flag_calls_in_wrapped_lazy_join(
    join_scope: LazyJoinToAdd, node: ast.SelectQuery, original_select_type: ast.SelectQueryType, context: HogQLContext
) -> None:
    """Raises when lazy_tables resolves `join_scope` inside the wrapper subquery of a table whose join condition reads
    it, `node` compares the join's `event` with flag calls, and the join's subquery scans `events` without pinning
    flag calls itself. The wrapper holds none of the filters of `node`, so `read_flag_calls_in_lazy_join` can neither
    move the pin there nor see the comparison to refuse it."""
    database = swap_database(context)
    if database is None or not context.flag_calls_only_in_flag_evaluations():
        return
    if not _compares_with_flag_calls(node, _join_event_reader(join_scope, original_select_type)):
        return
    subquery = join_scope.lazy_join.resolve_join_to_add(join_scope, context, node).table
    if not isinstance(subquery, ast.SelectQuery):
        return
    scan = EventsScan.of(subquery, partial(team_flag_key_compares_as_string, context), {}, database)
    if scan is None or scan.pins_flag_calls(filter_conjuncts(subquery), needs_flag_key=False):
        return
    join_name = _join_name(join_scope)
    raise flag_calls_only_in_flag_evaluations_error(
        f"a join condition reads a lazy join of the table that {join_name} comes from, so a filter on "
        f"{join_name}.event can't move into the join",
        FlagCallScope.join(join_name),
    )


def _join_name(join_scope: LazyJoinToAdd) -> str:
    return f"{join_scope.from_table}.{join_scope.lazy_join_type.field}"


def _join_event_reader(
    join_scope: LazyJoinToAdd, original_select_type: ast.SelectQueryType
) -> Callable[[ast.Expr], bool]:
    return partial(_reads_join_event, join_scope.to_table, original_select_type)


def _passes_rows_through(subquery: ast.SelectQuery) -> bool:
    # posthog.hogql.property imports posthog.schema, which lazy_tables must not load during django.setup().
    from posthog.hogql.property import has_aggregation, has_window_function  # noqa: PLC0415

    set_clauses = {
        field.name for field in dataclasses.fields(subquery) if getattr(subquery, field.name) not in (None, [], {})
    }
    return set_clauses <= _ROW_PRESERVING_CLAUSES and not any(
        has_aggregation(expr) or has_window_function(expr) for expr in subquery.select
    )


def _reads_join_event(to_table: str, original_select_type: ast.SelectQueryType, expr: ast.Expr) -> bool:
    field_type = event_field_type(expr)
    # lazy_tables can give each field of a join its own LazyJoinType. This check therefore compares the join's name.
    return (
        field_type is not None
        and isinstance(field_type.table_type, ast.LazyJoinType)
        and get_long_table_name(original_select_type, field_type.table_type) == to_table
    )


def _compares_with_flag_calls(node: AST, reads_join_event: Callable[[ast.Expr], bool]) -> bool:
    finder = _JoinEventComparisonFinder(reads_join_event)
    finder.visit(node)
    return finder.found


# A negated `=` or `IN` maps to no entry, because it keeps every event other than the compared ones.
_POSITIVE_OF_NEGATED = {
    ast.CompareOperationOp.NotEq: ast.CompareOperationOp.Eq,
    ast.CompareOperationOp.NotIn: ast.CompareOperationOp.In,
    ast.CompareOperationOp.GlobalNotIn: ast.CompareOperationOp.GlobalIn,
}


def _negated_operand(expr: ast.Expr) -> ast.Expr | None:
    if isinstance(expr, ast.Not):
        return expr.expr
    # The parser emits the NOT keyword as a call named "NOT". HogQL matches function names without case.
    if isinstance(expr, ast.Call) and expr.name.lower() == "not" and len(expr.args) == 1:
        return expr.args[0]
    return None


_AS_WRITTEN = frozenset({True})
_NEGATED = frozenset({False})
_EITHER = frozenset({True, False})


class _JoinEventComparisonFinder(SyntaxVisitor):
    """Finds a comparison that keeps only `$feature_flag_called` on the join's `event`. Each comparison is read with
    the NOTs above it: a NOT flips the comparisons under it, through AND and OR as De Morgan's laws do."""

    def __init__(self, reads_join_event: Callable[[ast.Expr], bool]) -> None:
        super().__init__()
        self.reads_join_event = reads_join_event
        self.found = False
        # True reads a comparison as written, and False reads it negated.
        self.polarities = _AS_WRITTEN

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        self._check(node)
        self._visit_opaque([node.left, node.right])

    def visit_not(self, node: ast.Not) -> None:
        self._visit_with(frozenset(not p for p in self.polarities), [node.expr])

    def visit_call(self, node: ast.Call) -> None:
        name = node.name.lower()
        if _negated_operand(node) is not None:
            self._visit_with(frozenset(not p for p in self.polarities), node.args)
        elif name in ("and", "or"):
            super().visit_call(node)
        elif comparison_of(node) is not None:
            self._check(node)
            self._visit_opaque(node.args)
        else:
            self._visit_opaque([*node.args, *(node.params or [])])

    def _visit_opaque(self, exprs: list[ast.Expr]) -> None:
        # Under a NOT, a node other than AND, OR and NOT can keep a comparison's values or their complement, so both
        # readings count. Without a NOT, a comparison is read as written, as the swap reads it.
        self._visit_with(_AS_WRITTEN if self.polarities == _AS_WRITTEN else _EITHER, exprs)

    def _visit_with(self, polarities: frozenset[bool], exprs: list[ast.Expr]) -> None:
        outer, self.polarities = self.polarities, polarities
        try:
            for expr in exprs:
                self.visit(expr)
        finally:
            self.polarities = outer

    def _check(self, expr: ast.Expr) -> None:
        comparison = comparison_of(expr)
        if comparison is None:
            return
        for as_written in self.polarities:
            op = comparison.op if as_written else _POSITIVE_OF_NEGATED.get(comparison.op)
            if op is None:
                continue
            values = compared_values(
                ast.CompareOperation(op=op, left=comparison.left, right=comparison.right), self.reads_join_event
            )
            if values is not None and any(is_flag_called(value) for value in values):
                self.found = True
