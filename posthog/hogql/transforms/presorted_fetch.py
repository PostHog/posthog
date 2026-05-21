"""AST-to-AST transform: resolve narrow row identifiers first, then fetch wide columns.

For an ``ORDER BY ... LIMIT n`` query that selects a wide column — the raw ``properties``
or ``elements_chain`` blob, or ``*`` — reading that blob for every candidate row before
sorting dominates the query cost. This transform rewrites::

    SELECT uuid, properties FROM events WHERE ... ORDER BY timestamp LIMIT 100

into::

    SELECT uuid, properties FROM events
    WHERE uuid IN (SELECT uuid FROM events WHERE ... ORDER BY timestamp LIMIT 100) AND ...
    ORDER BY timestamp LIMIT 100

so the sort runs over the narrow identifier only and the wide blob is read for the matched
rows alone. This generalizes the optimization that previously lived inside
``EventsQueryRunner`` so that raw ``HogQLQuery`` (and any other events query) benefits too.

The transform runs on the *unresolved* AST (before ``resolve_types``), like
``do_preaggregated_table_transforms``, because ``resolve_types`` is not re-entrant — it
raises if it revisits a node that already has a type. The single downstream resolution pass
types the rewritten tree naturally.

Exports:
* do_presorted_fetch_transform
"""

from dataclasses import dataclass
from typing import TypeVar, cast

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.property import has_aggregation
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

_T_AST = TypeVar("_T_AST", bound=AST)

# A query whose LIMIT exceeds this is left alone: the IN-set would be large and the outer
# re-scan needed to apply it stops paying for itself. Mirrors ClickHouse's own
# lazy-materialization row cap.
PRESORTED_MAX_LIMIT = 10000


@dataclass(frozen=True)
class _PresortedTable:
    # The identifier MUST be unique per row, or the IN-subquery rewrite is incorrect.
    identifier: str
    wide_columns: frozenset[str]


# Tables eligible for the rewrite, matched by their resolved Table subclass. Add new tables
# here once their unique identifier and wide columns are known.
_PRESORTED_TABLES: dict[type[Table], _PresortedTable] = {
    EventsTable: _PresortedTable(identifier="uuid", wide_columns=frozenset({"properties", "elements_chain"})),
}


class _WideFieldFinder(TraversingVisitor):
    """Detects references to a table's raw wide columns (and ``*``) within an expression.

    A *raw* reference reads the whole blob (``properties``, ``elements_chain`` or
    ``table.properties``); a value extraction (``properties.$foo``) does not count, since it
    can be sorted/selected cheaply. Subqueries are not descended into — a wide read nested in
    a subquery is that subquery's own concern.
    """

    def __init__(self, table_names: frozenset[str], wide_columns: frozenset[str]) -> None:
        super().__init__()
        self._table_names = table_names
        self._wide_columns = wide_columns
        self.found_wide: bool = False
        self.found_star: bool = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return

    def visit_field(self, node: ast.Field) -> None:
        chain = [str(c) for c in node.chain]
        if self._is_raw_wide(chain):
            self.found_wide = True
        elif self._is_star(chain):
            self.found_star = True

    def _is_raw_wide(self, chain: list[str]) -> bool:
        if len(chain) == 1:
            return chain[0] in self._wide_columns
        if len(chain) == 2:
            return chain[1] in self._wide_columns and chain[0] in self._table_names
        return False

    def _is_star(self, chain: list[str]) -> bool:
        if chain == ["*"]:
            return True
        return len(chain) == 2 and chain[1] == "*" and chain[0] in self._table_names


class _PresortedFetchTransformer(CloningVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self._context = context
        # CTE names visible at the current point in the tree. A CTE named like a registered
        # table shadows the real table, so we must not rewrite a FROM that resolves to it.
        self._cte_names_in_scope: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        added = {name for name in (node.ctes or {}) if name not in self._cte_names_in_scope}
        self._cte_names_in_scope |= added
        try:
            cloned = cast(ast.SelectQuery, super().visit_select_query(node))
            config = self._eligible(cloned)
            if config is not None:
                return self._rewrite(cloned, config)
            return cloned
        finally:
            self._cte_names_in_scope -= added

    def _eligible(self, node: ast.SelectQuery) -> _PresortedTable | None:
        select_from = node.select_from
        if select_from is None or select_from.next_join is not None:
            return None
        if not isinstance(select_from.table, ast.Field):
            return None
        if node.distinct or node.group_by or node.having or node.qualify:
            return None
        if node.array_join_list or node.array_join_op or node.window_exprs or node.prewhere:
            return None
        if node.limit_by is not None or node.limit_with_ties or node.limit_percent:
            return None
        if not node.order_by:
            return None

        limit = node.limit
        if not isinstance(limit, ast.Constant) or not isinstance(limit.value, int):
            return None
        if limit.value <= 0 or limit.value > PRESORTED_MAX_LIMIT:
            return None

        table_chain = [str(c) for c in select_from.table.chain]
        if len(table_chain) == 1 and table_chain[0] in self._cte_names_in_scope:
            return None

        if self._context.database is None:
            return None
        try:
            resolved = self._context.database.get_table(table_chain)
        except Exception:
            return None
        config = next((c for table_cls, c in _PRESORTED_TABLES.items() if isinstance(resolved, table_cls)), None)
        if config is None:
            return None

        if any(has_aggregation(expr) for expr in node.select):
            return None

        table_names = frozenset({table_chain[-1]} | ({select_from.alias} if select_from.alias else set()))

        # Sorting by the raw blob would force the inner (narrow) query to read it anyway,
        # defeating the optimization.
        for order_expr in node.order_by:
            finder = _WideFieldFinder(table_names, config.wide_columns)
            finder.visit(order_expr.expr)
            if finder.found_wide:
                return None

        # No benefit unless a wide blob is actually selected.
        if not self._select_reads_wide(node, table_names, config.wide_columns):
            return None

        return config

    @staticmethod
    def _select_reads_wide(node: ast.SelectQuery, table_names: frozenset[str], wide_columns: frozenset[str]) -> bool:
        for select_expr in node.select:
            finder = _WideFieldFinder(table_names, wide_columns)
            finder.visit(select_expr)
            if finder.found_wide or finder.found_star:
                return True
        return False

    def _rewrite(self, node: ast.SelectQuery, config: _PresortedTable) -> ast.SelectQuery:
        identifier = config.identifier
        limit_value = cast(int, cast(ast.Constant, node.limit).value)
        offset_value = (
            cast(int, node.offset.value)
            if isinstance(node.offset, ast.Constant) and isinstance(node.offset.value, int)
            else 0
        )

        # Reuse the outer FROM (table + alias, guaranteed join-free) so the cloned WHERE and
        # ORDER BY — which may reference the table alias — still resolve inside the subquery.
        inner = ast.SelectQuery(
            select=[ast.Field(chain=[identifier])],
            select_from=clone_expr(node.select_from, clear_types=True),
            where=clone_expr(node.where, clear_types=True) if node.where is not None else None,
            order_by=[clone_expr(order_expr, clear_types=True) for order_expr in (node.order_by or [])],
            limit=ast.Constant(value=limit_value + offset_value),
        )
        prefilter = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=[identifier]),
            right=inner,
        )
        node.where = ast.And(exprs=[prefilter, node.where]) if node.where is not None else prefilter
        return node


def do_presorted_fetch_transform(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Rewrite eligible ``ORDER BY ... LIMIT`` queries to sort by a narrow identifier first.

    Returns the original node unchanged when nothing is eligible. Must run before
    ``resolve_types``.
    """
    if not isinstance(node, ast.SelectQuery | ast.SelectSetQuery):
        return node
    if context.database is None:
        return node
    return cast(_T_AST, _PresortedFetchTransformer(context).visit(node))
