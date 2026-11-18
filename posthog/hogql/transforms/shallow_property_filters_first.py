"""Order the WHERE terms of a native JSON events read so a filter on a property runs before a filter inside one.

A property of the native events table is one path of a JSON column. A shallow filter (``properties.query_type``)
reads only that path. A deep filter reads a whole property as JSON text and parses it on every row it is evaluated
on: a path below the first level (``properties.query.source.accountId``), a JSON function over a property, or the
whole document.

ClickHouse evaluates the conditions it moves to PREWHERE in read steps, and a later step reads its columns only
where the earlier steps kept rows. It orders the steps by the stored size of the columns they read. It has a size
for a path of a JSON column only when ``allow_calculating_subcolumns_sizes_for_merge_tree_reading`` is on, and that
setting costs planning time on a table with many parts. Without it, two filters on one JSON column tie, and a tie
keeps the order of the query. HogQL knows which of the two filters parses a whole property, and ClickHouse does not.

The transform changes a WHERE only when a deep filter comes before a shallow filter on the same JSON column. Every
other query prints the same SQL. AND is commutative, so the rows do not change.
"""

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen


@frozen
class _JsonColumnReads:
    """The JSON columns of the events table that one WHERE term reads, split by how it reads them."""

    shallow: frozenset[str]
    deep: frozenset[str]


class _JsonColumnReadCollector(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context
        self.shallow: set[str] = set()
        self.deep: set[str] = set()
        self._inside_json_function = False

    def visit_property_access(self, node: ast.PropertyAccess) -> None:
        column = self._events_json_column(node.expr)
        if column is None:
            return
        if len(node.keys) > 1 or self._inside_json_function:
            self.deep.add(column)
        else:
            self.shallow.add(column)

    def visit_field(self, node: ast.Field) -> None:
        # `visit_property_access` does not descend, so a JSON column that reaches here is read as a whole document.
        column = self._events_json_column(node)
        if column is not None:
            self.deep.add(column)

    def visit_call(self, node: ast.Call) -> None:
        was_inside_json_function = self._inside_json_function
        self._inside_json_function = was_inside_json_function or "JSON" in node.name
        super().visit_call(node)
        self._inside_json_function = was_inside_json_function

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A subquery reads its own table, and the transform orders its WHERE on its own visit.
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def _events_json_column(self, expr: ast.Expr) -> str | None:
        if not isinstance(expr, ast.Field) or not isinstance(expr.type, ast.FieldType):
            return None
        table_type: ast.Type | None = expr.type.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            table_type = table_type.table_type
        if not isinstance(table_type, ast.TableType) or not isinstance(table_type.table, EventsTable):
            return None
        # `poe.properties` and `properties` share a logical name and are stored in different columns.
        database_field = expr.type.resolve_database_field(self.context)
        if not isinstance(database_field, StringJSONDatabaseField):
            return None
        return database_field.name


def _deep_filter_precedes_shallow_sibling(reads: list[_JsonColumnReads]) -> bool:
    deep_columns_so_far: set[str] = set()
    for term_reads in reads:
        if term_reads.deep:
            deep_columns_so_far |= term_reads.deep
        elif term_reads.shallow & deep_columns_so_far:
            return True
    return False


class _ShallowPropertyFiltersFirst(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)

        if node.where is None:
            return

        terms = top_level_conjuncts(node.where)
        reads = [self._reads_of(term) for term in terms]
        if not _deep_filter_precedes_shallow_sibling(reads):
            return

        # Only the deep filters move, and each group keeps its own order, so the query changes as little as possible.
        node.where = ast.And(
            exprs=[term for term, term_reads in zip(terms, reads) if not term_reads.deep]
            + [term for term, term_reads in zip(terms, reads) if term_reads.deep]
        )

    def _reads_of(self, term: ast.Expr) -> _JsonColumnReads:
        collector = _JsonColumnReadCollector(self.context)
        collector.visit(term)
        return _JsonColumnReads(shallow=frozenset(collector.shallow), deep=frozenset(collector.deep))


def order_shallow_property_filters_first(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Reorder every eligible WHERE in the tree. Mutates in place and returns the node."""
    _ShallowPropertyFiltersFirst(context).visit(node)
    return node
