"""Prefix an events ``ORDER BY timestamp`` with ``toDate(timestamp)`` so ClickHouse reads the table in sort-key order.

The events table is sorted by ``(team_id, toDate(timestamp), event, ...)``. ClickHouse reads a table in that order
and stops at the LIMIT only when the ORDER BY prefix matches the sort key syntactically or through a monotonic
function it knows. HogQL prints every events timestamp as ``toTimeZone(events.timestamp, tz)``, which ClickHouse
does not see through, so ``ORDER BY timestamp LIMIT n`` reads and sorts every matching row, even for a UTC team.

``toDate`` is monotonic in the instant, so ``ORDER BY toDate(ts) X, ts X`` is the same total order as
``ORDER BY ts X`` for either direction and the prefix changes no result. Index pruning already sees through the
wrapper, so the WHERE side needs nothing.

The transform runs only when ``HogQLContext.order_events_reads_by_sort_key`` is set. The sort key continues with
``event`` after the date, so the rows of one day are not in timestamp order, and ClickHouse must read and sort a
whole day before it returns the first row. That costs more than a parallel read when the range is short or the
filter is selective.
"""

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor, clone_expr


def order_events_reads_by_sort_key(node: _T_AST) -> _T_AST:
    """Add the sort-key prefix to every eligible select in the tree. Mutates in place and returns the node."""
    _EventsReadInOrderTransform().visit(node)
    return node


class _EventsReadInOrderTransform(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)

        if node.limit is None or not node.order_by:
            return

        first_key = node.order_by[0]
        timestamp_field = _events_timestamp_field(first_key)
        if timestamp_field is None:
            return

        # `_toDate` prints as `toDate` unconditionally. The public `toDate` maps to `toDateOrNull` unless the
        # printer can type its argument, and the sort key match needs the exact function name.
        prefix = ast.OrderExpr(
            expr=ast.Call(name="_toDate", args=[clone_expr(timestamp_field, clear_types=False)]),
            order=first_key.order,
        )
        node.order_by.insert(0, prefix)


def _events_timestamp_field(order_expr: ast.OrderExpr) -> ast.Field | None:
    """The physical ``events.timestamp`` field an ORDER BY key sorts by, or None when the key is anything else.

    Running the transform twice is a no-op: after the rewrite the first key is the ``toDate`` call, not a field.
    """
    # WITH FILL fabricates rows along the first key, so a new first key would change which rows get filled.
    if order_expr.with_fill is not None:
        return None

    # The property-type pass has already wrapped the column in toTimeZone, and a select alias can wrap it again.
    expr = order_expr.expr
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if isinstance(expr, ast.Call) and expr.name == "toTimeZone" and expr.args:
        expr = expr.args[0]
        while isinstance(expr, ast.Alias):
            expr = expr.expr

    if not isinstance(expr, ast.Field) or not _is_events_timestamp_type(expr.type):
        return None
    return expr


def _is_events_timestamp_type(type_: ast.Type | None) -> bool:
    # A computed select alias named `timestamp` resolves to its expression's type, not to the events FieldType.
    while isinstance(type_, ast.FieldAliasType):
        type_ = type_.type
    if not isinstance(type_, ast.FieldType) or type_.name != "timestamp":
        return False
    table_type = type_.table_type
    while isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)
