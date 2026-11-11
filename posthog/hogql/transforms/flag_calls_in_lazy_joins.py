from collections.abc import Callable
from functools import partial

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoinToAdd
from posthog.hogql.database.schema.util.where_clause_extractor import event_field_type
from posthog.hogql.property import has_aggregation
from posthog.hogql.resolver_utils import get_long_table_name
from posthog.hogql.transforms.events_predicate_pushdown import PREDICATE_SAFE_JOIN_TYPES
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import (
    EventsScan,
    FlagCallScope,
    SyntaxVisitor,
    _Resolve,
    and_conditions,
    compared_values,
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


def read_flag_calls_in_lazy_join(
    join_to_add: ast.JoinExpr,
    join_scope: LazyJoinToAdd,
    node: ast.SelectQuery,
    original_select_type: ast.SelectQueryType,
    context: HogQLContext,
    resolve: _Resolve[ast.SelectQuery],
) -> None:
    """Points the `events` scan in the subquery of `join_to_add` at `posthog.flag_evaluations` when `swap_flag_calls`
    accepts it, or raises when the organization's flag calls are only in `flag_evaluations` and the join would miss
    them. `node` is the SELECT that owns the join. It changes `join_to_add.table` in place.

    It acts only on a subquery that scans `events`, for an organization that reads flag calls from `flag_evaluations`.
    Without a pin from `node`, it runs `swap_flag_calls` only when `swaps_flag_calls` accepts the subquery.

    For an organization whose flag calls are only in `flag_evaluations`, a subquery that does not pin `event` to flag
    calls itself gets a pin on its own scan when both of these hold:

    - A top-level condition of the WHERE or PREWHERE of `node` pins the join's `event` to flag calls, so every row
      that `node` keeps has `event = '$feature_flag_called'` on the joined side. The condition is matched by the
      resolved type of `event`, not by its name.
    - The join type, without a `GLOBAL` prefix, is one of `PREDICATE_SAFE_JOIN_TYPES`. Each output row of those joins
      comes from one pair of rows, and the pin is false on the row a missing match produces. An ASOF or ANY join picks
      one row among several matches, so a filter before the join can pick a different row.
    - The subquery passes each row of its scan through on its own. A filter before a GROUP BY, an aggregate, a LIMIT or
      DISTINCT changes which rows come out.

    It raises when `node` compares the join's `event` with `$feature_flag_called` by `=` or `IN` and one of these
    does not hold. The function builds the pin on the subquery's scan, so no name from `node` has to resolve in the
    subquery.
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
    join_name = f"{join_scope.from_table}.{join_scope.lazy_join_type.field}"
    scope = FlagCallScope.join(join_name)
    pin: ast.Expr | None = None
    if database.flag_calls_only_in_flag_evaluations and not scan.pins_flag_calls(
        filter_conjuncts(subquery), needs_flag_key=False
    ):
        reads_join_event = partial(_reads_join_event, join_scope.to_table, original_select_type)
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
                f"the subquery of {join_name} groups, limits or aggregates its rows, so it can't take a filter on "
                "event before the join",
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
    if database is None or not database.flag_calls_only_in_flag_evaluations:
        return
    if not _compares_with_flag_calls(node, partial(_reads_join_event, join_scope.to_table, original_select_type)):
        return
    subquery = join_scope.lazy_join.resolve_join_to_add(join_scope, context, node).table
    if not isinstance(subquery, ast.SelectQuery):
        return
    scan = EventsScan.of(subquery, partial(team_flag_key_compares_as_string, context), {}, database)
    if scan is None or scan.pins_flag_calls(filter_conjuncts(subquery), needs_flag_key=False):
        return
    join_name = f"{join_scope.from_table}.{join_scope.lazy_join_type.field}"
    raise flag_calls_only_in_flag_evaluations_error(
        f"the query reads {join_name} in a join condition, so a filter on {join_name}.event can't move into the join",
        FlagCallScope.join(join_name),
    )


def _passes_rows_through(subquery: ast.SelectQuery) -> bool:
    return not (
        subquery.group_by
        or subquery.having
        or subquery.limit
        or subquery.offset
        or subquery.limit_by
        or subquery.distinct
        or subquery.array_join_op
        or subquery.window_exprs
        or any(has_aggregation(expr) for expr in subquery.select)
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


class _JoinEventComparisonFinder(SyntaxVisitor):
    def __init__(self, reads_join_event: Callable[[ast.Expr], bool]) -> None:
        super().__init__()
        self.reads_join_event = reads_join_event
        self.found = False

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        self._check(node)
        super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call) -> None:
        self._check(node)
        super().visit_call(node)

    def _check(self, expr: ast.Expr) -> None:
        values = compared_values(expr, self.reads_join_event)
        if values is not None and any(is_flag_called(value) for value in values):
            self.found = True
