"""Resolve-then-fetch (late materialization) for wide ``events`` scans with ``ORDER BY timestamp`` + ``LIMIT``.

When a query reads wide columns from ``events`` (the ``properties`` JSON blob, ``elements_chain``, or
``SELECT *``) and orders by ``timestamp`` with a ``LIMIT``, ClickHouse — even reading in primary-key order —
must materialize those wide columns for every granule it scans on the way to finding the top ``LIMIT`` rows.
For a selective filter that forces a deep scan, that means dragging megabytes of ``properties`` across rows
that are then discarded by the ``LIMIT``. This is the dominant cost (and OOM source) of the events-explorer
query shape.

The fix is the classic two-phase split — a strict superset of the hand-built "presorted optimization" that
``EventsQueryRunner`` used to do:

    SELECT <wide ...> FROM events WHERE <w> ORDER BY <ord> LIMIT n [OFFSET m]

becomes

    SELECT <wide ...> FROM events
    WHERE <w> AND (timestamp, uuid) IN (
        SELECT timestamp, uuid FROM events WHERE <w> ORDER BY <ord> LIMIT n + m
    )
    ORDER BY <ord> LIMIT n [OFFSET m]

The **inner** query resolves only the narrow ordering/identity columns ``(timestamp, uuid)`` — no wide data is
read while scanning to satisfy the order — and, when the order leads with ``timestamp``, ``timestamp_order_by``
makes it read in primary-key order and early-terminate. The **outer** query then point-fetches the wide columns
for only the resolved rows.

Two things make this a strict superset of the old runner split, so it is never worse than it was:

1. **Keep the outer filter** (``<w> AND (timestamp, uuid) IN ...``, not the ``IN`` alone). The events sort key
   is ``(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))``, so a predicate like
   ``event = ...`` sits high in the key and prunes whole granules. Dropping it and leaning on the ``IN`` would
   force ClickHouse to read every granule in the matched days — the ``IN`` only prunes to day granularity (see
   below) — which for a selective filter is catastrophically more data. The runner kept the filter; so do we.
2. **Match the ``(timestamp, uuid)`` pair**, not ``uuid`` alone (the runner used ``uuid``). ``uuid`` is the
   trailing sort-key column (stored as ``cityHash64(uuid)``), so ``uuid IN (...)`` cannot skip granules,
   whereas the concrete timestamps feed the ``toDate(timestamp)`` index and let the outer skip the granules
   that hold none of the matched rows. ``uuid`` is unique per event, so the pair selects *exactly* the
   inner-resolved rows; results are identical to the unsplit query.

This generalizes the runner's hand-built split: because it runs in the printer pipeline, every qualifying
query gets it — ad-hoc ``/query`` HogQL, the event taxonomy runner, and any other code path that scans wide
events with a ``LIMIT`` — not just one runner.

It runs **before** type resolution so the injected subquery flows through the normal
resolve / lazy-table / property-swap pipeline exactly like a hand-written one (the same reason
``EventsQueryRunner`` built its split on an unresolved AST). The only field references it introduces are the
``timestamp`` and ``uuid`` identity columns, qualified with the events table's alias (if any) so they resolve
against the single bare table; the ``FROM`` / ``WHERE`` / ``ORDER BY`` it copies into the inner query are
verbatim clones of the outer's, so they resolve identically.

The rewrite is intentionally narrow. It only fires when:

- the source is a single bare ``events`` table — no joins, ``ARRAY JOIN``, ``SAMPLE``, ``FINAL``, subquery
  source, or CTEs (lazy person/group joins implied by ``WHERE``/``SELECT`` are fine: they are reproduced by
  cloning, and resolve on the inner/outer independently),
- there is an ``ORDER BY`` and no term sorts by a *raw* wide column (the ``properties`` blob or
  ``elements_chain``) — this matches the runner's presorted-optimization breadth, so dropping the runner split
  never loses an optimization it had. A ``properties.$x`` extraction is fine. When the leading term is
  ``timestamp`` the inner additionally early-terminates (see ``timestamp_order_by``); other orders still
  benefit from the narrow inner sort + wide point-fetch,
- there is a constant ``LIMIT`` (and ``OFFSET``) within the standard returned-rows ceiling — the payoff is
  bounded point-fetching; a huge limit would just double-scan,
- the projection actually reads a wide column (``*``, ``properties``, or ``elements_chain``) — otherwise the
  split is pure overhead,
- there is no ``GROUP BY`` / aggregation, ``DISTINCT``, window function, ``WITH FILL``, ``HAVING``,
  ``QUALIFY``, ``PREWHERE``, ``LIMIT BY``, or ``LIMIT ... WITH TIES`` — these change row identity or set
  semantics so a per-row identity split would not be equivalent, and
- the query is not already resolve-then-fetched (so it composes safely with ``EventsQueryRunner``'s own split
  and never re-wraps its own inner query).

NB: like ``EventsQueryRunner``'s split, the inner ``LIMIT n + m`` means events sharing the exact timestamp at
the page boundary could in principle be ordered differently than a single full sort. In practice this is
immaterial — ``timestamp`` is ``DateTime64(6)`` — and it matches the existing behavior.
"""

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor, clone_expr

# Columns whose bytes dominate an events row; deferring their read to the final LIMIT rows is the win.
WIDE_EVENTS_COLUMNS = {"properties", "elements_chain"}


def optimize_events_resolve_then_fetch(node: ast.AST, context: HogQLContext) -> None:
    """Mutate ``node`` in place, splitting qualifying wide events scans into resolve + point-fetch."""
    EventsResolveThenFetchRewriter(context).visit(node)


def _unwrap_alias(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


class _NodeFinder(TraversingVisitor):
    """Sets ``found`` if the visited subtree contains a node matching ``_matches``."""

    def __init__(self) -> None:
        super().__init__()
        self.found = False


class _WindowFunctionFinder(_NodeFinder):
    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True


class _WideColumnFinder(_NodeFinder):
    def visit_field(self, node: ast.Field) -> None:
        # An asterisk expands to the full row (incl. properties + elements_chain), and any reference into
        # properties/elements_chain reads the wide blob (a `properties.$x` extraction still reads the column
        # unless materialized) — all worth deferring to the point-fetch.
        if any(part in WIDE_EVENTS_COLUMNS or part == "*" for part in node.chain):
            self.found = True


class _AggregationFinder(_NodeFinder):
    """Mirrors ``posthog.hogql.property.AggregationFinder`` but imports the function registry lazily.

    The registry (``find_hogql_aggregation``) is a side-effect-free dict lookup and is already loaded by the
    printer at call time, so this deferred import is a cached no-op. Importing it at module load — like
    importing ``posthog.hogql.property`` — would both hit the printer↔``posthog.models`` cycle and, worse,
    trigger ``posthog.models`` import side effects mid-query that alter the events ``*`` expansion.
    """

    def __init__(self) -> None:
        super().__init__()
        from posthog.hogql.functions import find_hogql_aggregation

        self._find_hogql_aggregation = find_hogql_aggregation

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass  # an aggregation inside a subquery does not make this query an aggregation

    def visit_call(self, node: ast.Call) -> None:
        if self._find_hogql_aggregation(node.name):
            self.found = True
            return
        for arg in node.args or []:
            self.visit(arg)


class _AliasReferenceFinder(_NodeFinder):
    """Sets ``found`` if any visited field references one of ``alias_names`` (an outer SELECT alias)."""

    def __init__(self, alias_names: set[str]) -> None:
        super().__init__()
        self._alias_names = alias_names

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and node.chain[0] in self._alias_names:
            self.found = True


def _references_select_alias(exprs: list[ast.Expr], alias_names: set[str]) -> bool:
    if not alias_names:
        return False
    finder = _AliasReferenceFinder(alias_names)
    for expr in exprs:
        finder.visit(expr)
    return finder.found


def _contains_window_function(exprs: list[ast.Expr]) -> bool:
    finder = _WindowFunctionFinder()
    for expr in exprs:
        finder.visit(expr)
    return finder.found


def _selects_wide_column(select: list[ast.Expr]) -> bool:
    finder = _WideColumnFinder()
    for expr in select:
        finder.visit(expr)
    return finder.found


class EventsResolveThenFetchRewriter(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # Recurse into subqueries / CTEs first, then rewrite this query. The injected inner subquery is added
        # afterwards and is never re-visited (it is also narrow, so it would not qualify anyway).
        super().visit_select_query(node)
        self._maybe_rewrite(node)

    def _maybe_rewrite(self, node: ast.SelectQuery) -> None:
        if not self._qualifies(node):
            return

        # Single bare events table (guaranteed by _qualifies): qualify the identity columns with the table's
        # alias if it has one (e.g. `e.timestamp` for `FROM events AS e`) so they resolve unambiguously. uuid
        # is unique per event, so (timestamp, uuid) identifies the row exactly.
        assert node.select_from is not None
        prefix = [node.select_from.alias] if node.select_from.alias else []
        timestamp_field = ast.Field(chain=[*prefix, "timestamp"])
        uuid_field = ast.Field(chain=[*prefix, "uuid"])

        assert isinstance(node.limit, ast.Constant)
        limit_plus_offset = node.limit.value + (
            node.offset.value if isinstance(node.offset, ast.Constant) and isinstance(node.offset.value, int) else 0
        )

        inner = ast.SelectQuery(
            select=[clone_expr(timestamp_field), clone_expr(uuid_field)],
            select_from=clone_expr(node.select_from),
            where=clone_expr(node.where) if node.where is not None else None,
            order_by=[clone_expr(order_expr) for order_expr in node.order_by] if node.order_by else None,
            limit=ast.Constant(value=limit_plus_offset),
        )

        # Strict superset of the runner's presorted optimization: KEEP the original WHERE and AND-in the
        # identity-pair prefilter (do not replace it). Keeping the filter preserves sort-key granule pruning on
        # the outer (e.g. an `event =` predicate, high in the sort key); the (timestamp, uuid) pair then prunes
        # the point-fetch to the matched days via toDate(timestamp). The outer keeps its SELECT / ORDER BY /
        # LIMIT / OFFSET; the printer adds the team_id guard to both scans.
        prefilter = ast.CompareOperation(
            left=ast.Tuple(exprs=[clone_expr(timestamp_field), clone_expr(uuid_field)]),
            op=ast.CompareOperationOp.In,
            right=inner,
        )
        node.where = ast.And(exprs=[node.where, prefilter]) if node.where is not None else prefilter

    def _qualifies(self, node: ast.SelectQuery) -> bool:
        """True if ``node`` is a wide bare-events scan we can safely split into resolve + point-fetch."""
        # Constant LIMIT (and OFFSET) within the standard ceiling — the payoff is bounded point-fetching.
        if not isinstance(node.limit, ast.Constant) or not isinstance(node.limit.value, int) or node.limit.value <= 0:
            return False
        if node.offset is not None and not (
            isinstance(node.offset, ast.Constant) and isinstance(node.offset.value, int) and node.offset.value >= 0
        ):
            return False
        offset_value = node.offset.value if isinstance(node.offset, ast.Constant) else 0
        if node.limit.value + offset_value > MAX_SELECT_RETURNED_ROWS:
            return False

        # No clause that changes row identity or set semantics — a per-row identity split would not be equivalent.
        if (
            node.distinct
            or node.group_by
            or node.having
            or node.qualify
            or node.prewhere
            or node.ctes
            or node.array_join_op is not None
            or node.array_join_list
            or node.limit_by is not None
            or node.limit_with_ties
            or node.limit_percent
            or node.window_exprs
        ):
            return False

        # Single bare events table: no joins, sample, FINAL, or subquery/CTE source.
        select_from = node.select_from
        if select_from is None or select_from.next_join is not None or select_from.sample is not None:
            return False
        if select_from.table_final:
            return False
        if not isinstance(select_from.table, ast.Field) or select_from.table.chain != ["events"]:
            return False

        # No aggregation or window function in the projection, and it must actually read a wide column —
        # otherwise the split is pure overhead (two narrow scans are slower than one).
        if self._select_has_aggregation(node.select):
            return False
        if _contains_window_function(node.select):
            return False
        if not _selects_wide_column(node.select):
            return False

        # There must be an ORDER BY, no term may sort by a raw wide column, and no WITH FILL / window function
        # anywhere in it (gap filling adds rows, windows span the set — neither survives a per-row split).
        if not node.order_by:
            return False
        if any(order_expr.with_fill is not None for order_expr in node.order_by):
            return False
        if _contains_window_function([order_expr.expr for order_expr in node.order_by]):
            return False
        if not self._order_by_qualifies(node.order_by):
            return False

        # The inner clones the ORDER BY but selects only (timestamp, uuid), so a term that references an outer
        # SELECT alias (e.g. `SELECT properties.x AS y ... ORDER BY y`) would be unresolvable inside it. WHERE
        # can't reference select aliases (scoping), so the ORDER BY is the only cloned clause at risk.
        alias_names = {item.alias for item in node.select if isinstance(item, ast.Alias)}
        if _references_select_alias([order_expr.expr for order_expr in node.order_by], alias_names):
            return False

        # Don't double-wrap: skip if already resolve-then-fetched (e.g. a hand-written `uuid IN (...)` split).
        if self._is_already_resolve_fetched(node.where):
            return False

        return True

    def _order_by_qualifies(self, order_by: list[ast.OrderExpr]) -> bool:
        """No order term may sort by a *raw* wide column; a ``properties.$x`` extraction is fine.

        Mirrors ``EventsQueryRunner._can_use_presorted_optimization``: ordering by the raw ``properties`` blob
        or ``elements_chain`` would need the wide column for the inner sort — exactly what we want to avoid —
        whereas any other order (``timestamp``, ``event``, ``created_at``, a function, a ``properties.$x``
        extraction) leaves the inner narrow. Matching this breadth means removing the runner split loses
        nothing it optimized.
        """
        for order_expr in order_by:
            expr = _unwrap_alias(order_expr.expr)
            if isinstance(expr, ast.Field) and expr.chain:
                first = expr.chain[0]
                if first in WIDE_EVENTS_COLUMNS and not (first == "properties" and len(expr.chain) >= 2):
                    return False
        return True

    def _select_has_aggregation(self, select: list[ast.Expr]) -> bool:
        finder = _AggregationFinder()
        for expr in select:
            finder.visit(expr)
        return finder.found

    def _is_already_resolve_fetched(self, where: ast.Expr | None) -> bool:
        if where is None:
            return False
        conjuncts = where.exprs if isinstance(where, ast.And) else [where]
        for conjunct in conjuncts:
            if (
                isinstance(conjunct, ast.CompareOperation)
                and conjunct.op == ast.CompareOperationOp.In
                and isinstance(conjunct.right, ast.SelectQuery)
                and self._references_uuid(conjunct.left)
            ):
                return True
        return False

    def _references_uuid(self, expr: ast.Expr) -> bool:
        if isinstance(expr, ast.Field):
            return bool(expr.chain) and expr.chain[-1] == "uuid"
        if isinstance(expr, ast.Tuple):
            return any(self._references_uuid(item) for item in expr.exprs)
        return False
