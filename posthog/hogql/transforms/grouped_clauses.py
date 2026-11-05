"""The clause split of a grouped `SELECT`, for the passes that must not rewrite an expression after grouping."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.database.schema.events import EVENTS_TABLE_TYPES
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.events_json import NULL_KEYS_COLUMNS

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

# The clauses that see the grouped rows. FROM, WHERE, PREWHERE and ARRAY JOIN see the source rows.
GROUPED_CLAUSES = ("select", "group_by", "having", "order_by", "qualify", "window_exprs", "limit_by", "interpolate")


def is_grouped(node: ast.SelectQuery) -> bool:
    return bool(node.group_by) or node.group_by_mode == "all"


def before_grouping(node: ast.SelectQuery) -> ast.SelectQuery:
    """A copy of the query with only the clauses that see the source rows."""
    empty: dict[str, Any] = {clause: [] if clause == "select" else None for clause in GROUPED_CLAUSES}
    return replace(node, **empty)


def visit_after_grouping(node: ast.SelectQuery, visit: Callable[[Any], Any]) -> dict[str, Any]:
    """Visits each expression of the clauses that see the grouped rows, and returns the clauses rebuilt from the results."""
    rebuilt: dict[str, Any] = {}
    for clause in GROUPED_CLAUSES:
        value = getattr(node, clause)
        if isinstance(value, list):
            rebuilt[clause] = [visit(expr) for expr in value]
        elif isinstance(value, dict):
            rebuilt[clause] = {name: visit(expr) for name, expr in value.items()}
        else:
            rebuilt[clause] = visit(value) if value is not None else None
    return rebuilt


class GroupedClauseTracker:
    """Tracks whether the expression under visit sees the grouped rows.

    An expression in a grouped clause has to stay a function of the group keys, so a pass with this tracker skips the
    rewrites that would read a source column there. An aggregate's arguments see the source rows whatever clause the
    aggregate is in, and a nested query starts its own split.
    """

    _in_grouped_clause: bool = False

    @contextmanager
    def _grouped_clause(self, in_grouped_clause: bool) -> Iterator[None]:
        was_in_grouped_clause = self._in_grouped_clause
        self._in_grouped_clause = in_grouped_clause
        try:
            yield
        finally:
            self._in_grouped_clause = was_in_grouped_clause

    @contextmanager
    def _call_arguments(self, node: ast.Call) -> Iterator[None]:
        """The context of a call's arguments, which see the source rows when the call is an aggregate."""
        if self._in_grouped_clause and find_hogql_aggregation(node.name):
            with self._grouped_clause(False):
                yield
        else:
            yield


WHOLE_DOCUMENT_GROUPING_ERROR = (
    "Can't group by the whole properties column. "
    "Group by the properties you need, like properties.$browser, or by uuid for one row per event."
)


class _AggregateFinder(TraversingVisitor):
    found = False

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name):
            self.found = True
        else:
            super().visit_call(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        """A subquery's aggregates group the subquery's rows."""


def _has_aggregate(node: ast.Expr) -> bool:
    finder = _AggregateFinder()
    finder.visit(node)
    return finder.found


class _ImplicitGroupingKeys(TraversingVisitor):
    """Collects the keys GROUP BY ALL takes from a select column: its largest parts that hold no aggregate."""

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[ast.Expr] = []

    def visit(self, node: AST | None) -> None:
        if isinstance(node, ast.Call) and find_hogql_aggregation(node.name):
            return
        if isinstance(node, ast.Expr) and not _has_aggregate(node):
            self.keys.append(node)
            return
        super().visit(node)


def _grouping_keys(node: ast.SelectQuery) -> list[ast.Expr]:
    """The keys ClickHouse groups by: an ordinal names a select column, a tuple is one key per element, and
    GROUP BY ALL takes the largest aggregate-free parts of every select column."""
    if node.group_by_mode == "all":
        implicit = _ImplicitGroupingKeys()
        for expr in node.select:
            implicit.visit(expr)
        return implicit.keys
    keys: list[ast.Expr] = []
    for group in node.group_by or []:
        for key in group.exprs if isinstance(group, ast.GroupingSet) else [group]:
            if isinstance(key, ast.Constant) and type(key.value) is int and 1 <= key.value <= len(node.select):
                key = node.select[key.value - 1]
            if isinstance(key, ast.Tuple):
                keys.extend(key.exprs)
            elif isinstance(key, ast.Call) and key.name == "tuple":
                keys.extend(key.args)
            else:
                keys.append(key)
    return keys


def _reads_events_json_document(field_type: ast.Type | None, context: "HogQLContext") -> bool:
    """Whether a field reads a JSON document of the events table, through any alias, subquery, CTE, view or union."""
    while isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type
    if not isinstance(field_type, ast.FieldType):
        return False
    table_type: ast.Type = field_type.table_type
    if isinstance(table_type, ast.CTETableAliasType):
        table_type = table_type.cte_table_type
    if isinstance(table_type, (ast.SelectQueryAliasType, ast.CTETableType, ast.SelectViewType)):
        table_type = table_type.select_query_type
    while isinstance(table_type, ast.SelectSetQueryType):
        table_type = table_type.types[0]
    if isinstance(table_type, ast.SelectQueryType):
        return _reads_events_json_document(table_type.columns.get(field_type.name), context)
    if not isinstance(table_type, ast.BaseTableType):
        return False
    database_field = field_type.resolve_database_field(context)
    # The native table stores the columns that have a null-keys companion as JSON and reads their keys as subcolumns.
    return (
        isinstance(table_type.resolve_database_table(context), EVENTS_TABLE_TYPES)
        and isinstance(database_field, StringJSONDatabaseField)
        and database_field.name in NULL_KEYS_COLUMNS
    )


def raise_on_whole_document_grouping(node: ast.SelectQuery, context: "HogQLContext") -> None:
    """Rejects a JSON document of the events table, `properties` or `person_properties`, as a grouping key.

    The native events table reads a key as a subcolumn, and ClickHouse does not accept the subcolumn
    `properties.$browser` as a function of the key `properties`, so a key read after `GROUP BY properties` fails
    there while the legacy table accepts it. Both tables reject the key so a query cannot work on one and fail on
    the other.
    """
    for key in _grouping_keys(node):
        while isinstance(key, ast.Alias):
            key = key.expr
        if isinstance(key, ast.Field) and _reads_events_json_document(key.type, context):
            raise QueryError(WHOLE_DOCUMENT_GROUPING_ERROR, node=key)
