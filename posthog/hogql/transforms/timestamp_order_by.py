"""Rewrite ``ORDER BY timestamp`` on the events table to lead with the sort-key prefix.

The events table is sorted by
``(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))`` and
partitioned by ``toYYYYMM(timestamp)``.

HogQL emits ``ORDER BY toTimeZone(timestamp, <project_tz>)`` for timestamp ordering (see
``PropertySwapper.visit_field``). That expression is not a prefix of the sort key — the key
stores ``toDate(timestamp)`` at day granularity in UTC — so ClickHouse's
``optimize_read_in_order`` cannot apply and a ``LIMIT`` cannot early-terminate: the engine
reads every matching row and sorts it.

Because every events query is printed with a ``team_id = X`` equality guard (see
``team_id_guard_for_table``), the first sort-key column is always fixed. That makes
``toDate(timestamp)`` the effective leading order, so we rewrite

    ORDER BY toTimeZone(timestamp, tz) D   [LIMIT n]

into

    ORDER BY toDate(timestamp) D, timestamp D   [LIMIT n]

``toTimeZone`` only changes display, not the underlying instant, and is order preserving;
``toDate`` (UTC) is monotonic non-decreasing in the instant. Therefore, for any direction D::

    ORDER BY toDate(timestamp) D, timestamp D
        ≡ ORDER BY timestamp D
        ≡ ORDER BY toTimeZone(timestamp, tz) D

The leading ``toDate(timestamp)`` term now matches the sort-key prefix, so ClickHouse reads
granules in primary-key order and a ``LIMIT`` can stop early instead of scanning the full
range. The ``timestamp`` tiebreaker preserves exact within-day ordering. This is the ORDER BY
analogue of the WHERE-clause rewrite in
``PropertySwapper._move_timezone_from_field_to_constant``.

The rewrite also sets ``read_in_order_use_buffering = 0`` on the query. ClickHouse's default
read-ahead buffering for read-in-order keeps reading granules past the point a ``LIMIT`` is
satisfied, so without disabling it the rewritten query over-reads by an order of magnitude and
its peak memory balloons (read-in-order's merge buffer). Disabling buffering is what turns
read-in-order into actual early termination — on a multi-billion-row team this took a
``ORDER BY timestamp DESC LIMIT 100`` scan from ~1.5B rows / 46 GiB down to ~36M rows / 1 GiB
at the same peak memory as the original.

The rewrite runs after the property swapper (so the timestamp is already wrapped in
``toTimeZone``) and is intentionally narrow — it only fires when:

- the term resolves to the events table's ``timestamp`` column (not ``created_at``, not other
  tables whose sort keys differ),
- ``timestamp`` is the *leading* ORDER BY term (read-in-order only helps the first term),
- there is a ``LIMIT`` (the payoff is early termination; without one the extra term is noise),
- there is no ``GROUP BY`` (the target is the raw-event scan, not an aggregation), and
- the term has no ``WITH FILL`` (gap filling has its own ordering semantics).

Only the ORDER BY is touched; the SELECT projection keeps the project timezone, so displayed
timestamp values are unchanged.
"""

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DateTimeDatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor, clone_expr


def optimize_timestamp_order_by(node: ast.Expr, context: HogQLContext) -> None:
    """Mutate ``node`` in place, expanding qualifying events ``ORDER BY timestamp`` terms."""
    TimestampOrderByRewriter(context).visit(node)


def _unwrap_alias(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


class TimestampOrderByRewriter(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # Recurse into subqueries, CTEs and joins first, then rewrite this query's ORDER BY.
        super().visit_select_query(node)
        self._rewrite_leading_timestamp_order(node)

    def _rewrite_leading_timestamp_order(self, node: ast.SelectQuery) -> None:
        # read-in-order only pays off when a LIMIT can early-terminate, and only on a raw
        # event scan — aggregations don't read in primary-key order.
        if not node.order_by or node.limit is None or node.group_by:
            return

        leading = node.order_by[0]
        if leading.with_fill is not None:
            return

        bare_timestamp = self._events_timestamp_field(leading.expr)
        if bare_timestamp is None:
            return

        # ORDER BY toDate(timestamp) D, timestamp D, <rest...> is order-equivalent to the
        # original leading `timestamp D, <rest...>`, but the leading toDate(timestamp) now
        # matches the events sort-key prefix (team_id is fixed by the printed team_id guard).
        # Both inner fields must be the bare timestamp: toDate(toTimeZone(timestamp, tz)) is
        # the project-local date and would NOT match the UTC toDate(timestamp) in the key.
        node.order_by = [
            ast.OrderExpr(expr=ast.Call(name="toDate", args=[clone_expr(bare_timestamp)]), order=leading.order),
            ast.OrderExpr(expr=clone_expr(bare_timestamp), order=leading.order),
            *node.order_by[1:],
        ]

        # Engaging read-in-order is only half the win: ClickHouse's default read-ahead buffering
        # (read_in_order_use_buffering=1) keeps reading granules past the LIMIT, so the scan
        # over-reads by an order of magnitude and peak memory balloons. Disabling it lets the
        # LIMIT actually early-terminate. Preserve any explicit value the query already carries.
        if node.settings is None:
            node.settings = HogQLQuerySettings()
        if node.settings.read_in_order_use_buffering is None:
            node.settings.read_in_order_use_buffering = False

    def _events_timestamp_field(self, expr: ast.Expr) -> ast.Field | None:
        """Return the bare events ``timestamp`` Field if ``expr`` orders by it (bare, or
        wrapped in a single ``toTimeZone``), otherwise None."""
        inner = _unwrap_alias(expr)

        # The property swapper wraps the bare timestamp field in toTimeZone(field, project_tz).
        # Peel exactly one layer to recover the bare field whose toDate matches the sort key.
        if isinstance(inner, ast.Call) and inner.name == "toTimeZone" and len(inner.args) >= 1:
            inner = _unwrap_alias(inner.args[0])

        if not isinstance(inner, ast.Field):
            return None

        field_type = inner.type
        if isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if not isinstance(field_type, ast.FieldType):
            return None

        database_field = field_type.resolve_database_field(self.context)
        if not isinstance(database_field, DateTimeDatabaseField) or database_field.name != "timestamp":
            return None

        # Must be the events table specifically — its sort key leads with toDate(timestamp).
        # Other tables with a "timestamp" column (sessions, warehouse, …) have different keys.
        table_type = field_type.table_type
        if not isinstance(table_type, ast.BaseTableType):
            return None
        if not isinstance(table_type.resolve_database_table(self.context), EventsTable):
            return None

        return inner
