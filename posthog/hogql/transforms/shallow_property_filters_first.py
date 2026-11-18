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

The transform moves a shallow filter in front of the first deep filter on the same JSON column of the same scan.
Only a comparison of a property with constants moves, because it cannot throw on a row that a filter in front of it
would have rejected. Every other filter keeps its place, so a filter that guards a later conversion still runs
before it. Every query without such a pair prints the same SQL.
"""

from collections import defaultdict

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

# The casts the property type pass adds. Each prints as a conversion that returns NULL when it cannot convert.
_PROPERTY_TYPE_CASTS = frozenset({"toString", "toFloat", "toBool", "toDateTime", "transform"})

_COMPARISONS_WITH_CONSTANTS = frozenset(
    {
        ast.CompareOperationOp.Eq,
        ast.CompareOperationOp.NotEq,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.In,
        ast.CompareOperationOp.NotIn,
    }
)


@frozen
class _JsonColumn:
    """One JSON column of one scan of the events table."""

    scan: str | None
    name: str


@frozen
class _FilterReads:
    """How one WHERE term reads the JSON columns of the events table."""

    deep: frozenset[_JsonColumn]
    movable_shallow: _JsonColumn | None


def _events_json_column(expr: ast.Expr, context: HogQLContext) -> _JsonColumn | None:
    if not isinstance(expr, ast.Field) or not isinstance(expr.type, ast.FieldType):
        return None
    scan: str | None = None
    table_type: ast.Type | None = expr.type.table_type
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
        # Two scans of events differ only by alias, and a filter on one says nothing about the rows of the other.
        if scan is None and isinstance(table_type, ast.TableAliasType):
            scan = table_type.alias
        table_type = table_type.table_type
    if not isinstance(table_type, ast.TableType) or not isinstance(table_type.table, EventsTable):
        return None
    # `poe.properties` and `properties` share a logical name and are stored in different columns.
    database_field = expr.type.resolve_database_field(context)
    if not isinstance(database_field, StringJSONDatabaseField):
        return None
    return _JsonColumn(scan=scan, name=database_field.name)


class _DeepReadCollector(TraversingVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context
        self.deep: set[_JsonColumn] = set()
        self._inside_json_function = False

    def visit_property_access(self, node: ast.PropertyAccess) -> None:
        if len(node.keys) > 1 or self._inside_json_function:
            column = _events_json_column(node.expr, self.context)
            if column is not None:
                self.deep.add(column)

    def visit_field(self, node: ast.Field) -> None:
        # `visit_property_access` does not descend, so a JSON column that reaches here is read as a whole document.
        column = _events_json_column(node, self.context)
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


def _is_constant_operand(expr: ast.Expr) -> bool:
    if isinstance(expr, (ast.Tuple, ast.Array)):
        return all(isinstance(item, ast.Constant) for item in expr.exprs)
    return isinstance(expr, ast.Constant)


def _shallow_comparison_column(term: ast.Expr, context: HogQLContext) -> _JsonColumn | None:
    """The JSON column `term` reads, when `term` compares one property with constants and does nothing else."""
    if not isinstance(term, ast.CompareOperation) or term.op not in _COMPARISONS_WITH_CONSTANTS:
        return None
    for operand, other in ((term.left, term.right), (term.right, term.left)):
        if not _is_constant_operand(other):
            continue
        # The resolver wraps a property read in a hidden alias, and the property type pass wraps a typed one in a cast.
        while True:
            if isinstance(operand, ast.Alias):
                operand = operand.expr
            elif isinstance(operand, ast.Call) and operand.name in _PROPERTY_TYPE_CASTS and operand.args:
                operand = operand.args[0]
            else:
                break
        if isinstance(operand, ast.PropertyAccess) and len(operand.keys) == 1:
            return _events_json_column(operand.expr, context)
    return None


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

        first_deep_filter: dict[_JsonColumn, int] = {}
        for index, term_reads in enumerate(reads):
            for column in term_reads.deep:
                first_deep_filter.setdefault(column, index)

        moves_in_front_of: defaultdict[int, list[int]] = defaultdict(list)
        for index, term_reads in enumerate(reads):
            if term_reads.movable_shallow is None:
                continue
            deep_index = first_deep_filter.get(term_reads.movable_shallow)
            if deep_index is not None and deep_index < index:
                moves_in_front_of[deep_index].append(index)
        if not moves_in_front_of:
            return

        moved = {index for indexes in moves_in_front_of.values() for index in indexes}
        ordered: list[ast.Expr] = []
        for index, term in enumerate(terms):
            ordered.extend(terms[shallow_index] for shallow_index in moves_in_front_of.get(index, ()))
            if index not in moved:
                ordered.append(term)
        node.where = ast.And(exprs=ordered)

    def _reads_of(self, term: ast.Expr) -> _FilterReads:
        collector = _DeepReadCollector(self.context)
        collector.visit(term)
        return _FilterReads(
            deep=frozenset(collector.deep), movable_shallow=_shallow_comparison_column(term, self.context)
        )


def order_shallow_property_filters_first(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Reorder every eligible WHERE in the tree. Mutates in place and returns the node."""
    _ShallowPropertyFiltersFirst(context).visit(node)
    return node
