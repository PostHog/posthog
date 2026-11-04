"""Finds reads of the events table that no lower time bound restricts.

`events` is partitioned by month, so a read without a lower bound on `timestamp` opens every
partition the team ever wrote to. The check runs on a resolved AST and answers per read: each
`events` table in a FROM or JOIN needs its own bound. A bound counts when it is a top-level
conjunct of WHERE or PREWHERE, in the select that reads the table or in an enclosing select that
filters a column taken from that table's `timestamp`. A point lookup by `uuid` also counts.
"""

from typing import Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import (
    extract_uuid_constants,
    top_level_conjuncts,
    unwrap_table_alias_type,
)
from posthog.hogql.helpers.timestamp_visitor import (
    IsSimpleTimestampFieldExpressionVisitor,
    is_time_or_interval_constant,
)
from posthog.hogql.visitor import TraversingVisitor

_TIMESTAMP_COLUMN = "timestamp"
_UUID_COLUMN = "uuid"
_LOWER_BOUND_OPS = frozenset(
    {ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Eq, ast.CompareOperationOp.In}
)
_FLIPPED_LOWER_BOUND_OPS = frozenset(
    {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Eq}
)
_POINT_LOOKUP_OPS = frozenset({ast.CompareOperationOp.Eq, ast.CompareOperationOp.In})


def reads_events_without_lower_bound(
    resolved_query: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext
) -> bool:
    scan = _SelectScan()
    scan.visit(resolved_query)
    reads: set[int] = set()
    restricted: set[int] = set()
    for select in scan.selects:
        reads.update(id(table_type) for table_type in _events_table_types(select))
        for clause in (select.where, select.prewhere):
            if clause is None:
                continue
            for conjunct in top_level_conjuncts(clause):
                restricted |= _lower_bounded_tables(conjunct, context, scan.alias_exprs)
                restricted |= _uuid_lookup_tables(conjunct)
    return not reads <= restricted


class _SelectScan(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[ast.SelectQuery] = []
        self.alias_exprs: dict[int, ast.Expr] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        super().visit_select_query(node)

    def visit_alias(self, node: ast.Alias) -> None:
        self.alias_exprs[id(node.type)] = node.expr
        super().visit_alias(node)


def _is_events_table(table_type: Optional[ast.Type]) -> bool:
    unwrapped = unwrap_table_alias_type(table_type)
    return isinstance(unwrapped, ast.TableType) and isinstance(unwrapped.table, EventsTable)


def _events_table_types(select: ast.SelectQuery) -> list[ast.Type]:
    table_types: list[ast.Type] = []
    join = select.select_from
    while join is not None:
        if join.type is not None and _is_events_table(join.type):
            table_types.append(join.type)
        join = join.next_join
    return table_types


def _subquery_column_types(table_type: Optional[ast.Type], name: str) -> list[ast.Type]:
    if isinstance(table_type, ast.SelectQueryAliasType | ast.CTETableType | ast.SelectViewType):
        return _subquery_column_types(table_type.select_query_type, name)
    if isinstance(table_type, ast.SelectSetQueryType):
        return [column for branch in table_type.types for column in _subquery_column_types(branch, name)]
    if isinstance(table_type, ast.SelectQueryType) and name in table_type.columns:
        return [table_type.columns[name]]
    return []


class _EventsTimestampVisitor(IsSimpleTimestampFieldExpressionVisitor):
    """Accepts an order-preserving expression of an events `timestamp` and records which tables it reads.

    The base visitor decides which wrappers keep the order. This subclass also accepts `toDate`
    and every `toStartOf*` function, and it does not change the base visitor, because the sessions
    pushdown in where_clause_extractor.py uses the base visitor. A field is followed through
    select aliases and subquery columns down to the events table it comes from.
    """

    def __init__(self, context: HogQLContext, alias_exprs: dict[int, ast.Expr]) -> None:
        super().__init__(context)
        self.alias_exprs = alias_exprs
        self.events_table_types: list[ast.Type] = []
        self._followed: set[int] = set()

    def visit_field(self, node: ast.Field) -> bool:
        return self._derives_from_events_timestamp(node.type)

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)

    def visit_call(self, node: ast.Call) -> bool:
        if node.args and (node.name == "toDate" or node.name.startswith("toStartOf")):
            return self.visit(node.args[0])
        return super().visit_call(node)

    def _derives_from_events_timestamp(self, field_type: Optional[ast.Type]) -> bool:
        if field_type is None or id(field_type) in self._followed:
            return False
        self._followed.add(id(field_type))
        if isinstance(field_type, ast.FieldAliasType):
            alias_expr = self.alias_exprs.get(id(field_type))
            if alias_expr is not None:
                return self.visit(alias_expr)
            return self._derives_from_events_timestamp(field_type.type)
        if not isinstance(field_type, ast.FieldType):
            return False
        if field_type.name == _TIMESTAMP_COLUMN and _is_events_table(field_type.table_type):
            self.events_table_types.append(field_type.table_type)
            return True
        columns = _subquery_column_types(field_type.table_type, field_type.name)
        return bool(columns) and all(self._derives_from_events_timestamp(column) for column in columns)


def _timestamp_tables(expr: ast.Expr, context: HogQLContext, alias_exprs: dict[int, ast.Expr]) -> set[int]:
    visitor = _EventsTimestampVisitor(context, alias_exprs)
    if not visitor.visit(expr):
        return set()
    return {id(table_type) for table_type in visitor.events_table_types}


def _is_constant(expr: ast.Expr) -> bool:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if isinstance(expr, ast.SelectQuery | ast.SelectSetQuery):
        return True
    return is_time_or_interval_constant(expr)


def _lower_bounded_tables(expr: ast.Expr, context: HogQLContext, alias_exprs: dict[int, ast.Expr]) -> set[int]:
    if isinstance(expr, ast.Or) or (isinstance(expr, ast.Call) and expr.name == "or"):
        branches = expr.exprs if isinstance(expr, ast.Or) else expr.args
        bounded_per_branch = [
            set().union(
                *(_lower_bounded_tables(conjunct, context, alias_exprs) for conjunct in top_level_conjuncts(branch))
            )
            for branch in branches
        ]
        return set.intersection(*bounded_per_branch) if bounded_per_branch else set()
    if isinstance(expr, ast.CompareOperation):
        bounded: set[int] = set()
        if expr.op in _LOWER_BOUND_OPS and _is_constant(expr.right):
            bounded |= _timestamp_tables(expr.left, context, alias_exprs)
        if expr.op in _FLIPPED_LOWER_BOUND_OPS and _is_constant(expr.left):
            bounded |= _timestamp_tables(expr.right, context, alias_exprs)
        return bounded
    if isinstance(expr, ast.BetweenExpr) and not expr.negated and _is_constant(expr.low):
        return _timestamp_tables(expr.expr, context, alias_exprs)
    return set()


def _uuid_lookup_tables(expr: ast.Expr) -> set[int]:
    if not isinstance(expr, ast.CompareOperation) or expr.op not in _POINT_LOOKUP_OPS:
        return set()
    column = expr.left
    while isinstance(column, ast.Alias):
        column = column.expr
    field_type = column.type if isinstance(column, ast.Field) else None
    if (
        isinstance(field_type, ast.FieldType)
        and field_type.name == _UUID_COLUMN
        and _is_events_table(field_type.table_type)
        and extract_uuid_constants(expr.right)
    ):
        return {id(field_type.table_type)}
    return set()
