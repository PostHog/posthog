"""Finds reads of the events table that no lower time bound restricts.

`events` is partitioned by month, so a read without a lower bound on `timestamp` opens every
partition the team ever wrote to. The check runs on a resolved AST and answers per read: each
`events` table in a FROM or JOIN needs its own bound. A bound counts when it is a top-level
conjunct of WHERE or PREWHERE, in the select that reads the table or in an enclosing select that
filters a column taken from that table's `timestamp`. A point lookup by `uuid` also counts.

An enclosing filter does not count across a LIMIT, LIMIT BY or window function in the inner select,
because moving the filter inside would change the result, so it cannot restrict the read. It also
does not count for a CTE that the query references more than once, because the filter restricts
only one of those reads.

The check reads the shape of the query and not the value of the bound, so `timestamp > '1970-01-01'`
passes. It guides callers and does not guarantee a scan size.
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
    IsTimeOrIntervalConstantVisitor,
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
_ORDER_PRESERVING_FUNCTIONS = frozenset({"toDate", "toDateTime64", "toUnixTimestamp"})
_DATE_TRUNC_FUNCTIONS = frozenset({"dateTrunc", "date_trunc"})


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
                restricted |= _lower_bounded_tables(conjunct, context, scan)
                restricted |= _uuid_lookup_tables(conjunct)
    return not reads <= restricted


class _SelectScan(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[ast.SelectQuery] = []
        self.alias_exprs: dict[int, ast.Expr] = {}
        self.pushdown_blocked: set[int] = set()
        self._referenced_ctes: set[int] = set()
        self._enclosing_selects: list[ast.SelectQuery] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        if node.limit is not None or node.limit_by is not None:
            self.pushdown_blocked.add(id(node.type))
        self._enclosing_selects.append(node)
        super().visit_select_query(node)
        self._enclosing_selects.pop()

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        if self._enclosing_selects:
            self.pushdown_blocked.add(id(self._enclosing_selects[-1].type))
        super().visit_window_function(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table_type = node.type.cte_table_type if isinstance(node.type, ast.CTETableAliasType) else node.type
        if isinstance(table_type, ast.CTETableType):
            cte_key = id(table_type.select_query_type)
            if cte_key in self._referenced_ctes:
                self.pushdown_blocked.add(cte_key)
            self._referenced_ctes.add(cte_key)
        super().visit_join_expr(node)

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


def _subquery_column_types(table_type: Optional[ast.Type], name: str, blocked: set[int]) -> list[ast.Type]:
    if isinstance(table_type, ast.CTETableAliasType):
        return _subquery_column_types(table_type.cte_table_type, name, blocked)
    if isinstance(table_type, ast.SelectQueryAliasType | ast.CTETableType | ast.SelectViewType):
        return _subquery_column_types(table_type.select_query_type, name, blocked)
    if id(table_type) in blocked:
        return []
    if isinstance(table_type, ast.SelectSetQueryType):
        return [column for branch in table_type.types for column in _subquery_column_types(branch, name, blocked)]
    if isinstance(table_type, ast.SelectQueryType) and name in table_type.columns:
        return [table_type.columns[name]]
    return []


class _EventsTimestampVisitor(IsSimpleTimestampFieldExpressionVisitor):
    """Accepts an order-preserving expression of an events `timestamp` and records which tables it reads.

    The base visitor decides which wrappers keep the order. This subclass also accepts more order
    preserving functions and is stricter about arithmetic, because the base visitor ignores the
    operator and `now() - timestamp > 86400` is an upper bound. It does not change the base visitor,
    because the sessions pushdown in where_clause_extractor.py uses the base visitor. A field is
    followed through select aliases and subquery columns down to the events table it comes from.

    A node type with no visit method is not a timestamp. It must not raise, because the caller
    treats an exception as a failed check and skips the whole query.
    """

    def __init__(self, context: HogQLContext, scan: _SelectScan) -> None:
        super().__init__(context)
        self.scan = scan
        self.events_table_types: list[ast.Type] = []
        self._followed: set[int] = set()

    def visit_unknown(self, node: ast.AST) -> bool:
        return False

    def visit_field(self, node: ast.Field) -> bool:
        return self._derives_from_events_timestamp(node.type)

    def visit_alias(self, node: ast.Alias) -> bool:
        return self.visit(node.expr)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> bool:
        if node.op == ast.ArithmeticOperationOp.Add:
            return (self.visit(node.left) and _is_constant(node.right)) or (
                self.visit(node.right) and _is_constant(node.left)
            )
        if node.op == ast.ArithmeticOperationOp.Sub:
            return self.visit(node.left) and _is_constant(node.right)
        return False

    def visit_call(self, node: ast.Call) -> bool:
        if node.args and (node.name in _ORDER_PRESERVING_FUNCTIONS or node.name.startswith("toStartOf")):
            return self.visit(node.args[0])
        if node.name in _DATE_TRUNC_FUNCTIONS and len(node.args) >= 2:
            return self.visit(node.args[1])
        return super().visit_call(node)

    def _derives_from_events_timestamp(self, field_type: Optional[ast.Type]) -> bool:
        if field_type is None or id(field_type) in self._followed:
            return False
        self._followed.add(id(field_type))
        if isinstance(field_type, ast.FieldAliasType):
            alias_expr = self.scan.alias_exprs.get(id(field_type))
            if alias_expr is not None:
                return self.visit(alias_expr)
            return self._derives_from_events_timestamp(field_type.type)
        if not isinstance(field_type, ast.FieldType):
            return False
        if field_type.name == _TIMESTAMP_COLUMN and _is_events_table(field_type.table_type):
            self.events_table_types.append(field_type.table_type)
            return True
        columns = _subquery_column_types(field_type.table_type, field_type.name, self.scan.pushdown_blocked)
        # Evaluate every column before `any`, so that each union branch records its events table.
        derived = [self._derives_from_events_timestamp(column) for column in columns]
        return any(derived)


def _timestamp_tables(expr: ast.Expr, context: HogQLContext, scan: _SelectScan) -> set[int]:
    visitor = _EventsTimestampVisitor(context, scan)
    if not visitor.visit(expr):
        return set()
    return {id(table_type) for table_type in visitor.events_table_types}


class _ConstantVisitor(IsTimeOrIntervalConstantVisitor):
    """Accepts an expression that reads no column of the row, so that any function of constants counts."""

    def __init__(self) -> None:
        super().__init__(None)

    def visit_unknown(self, node: ast.AST) -> bool:
        return False

    def visit_select_query(self, node: ast.SelectQuery) -> bool:
        return True

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> bool:
        return True

    def visit_call(self, node: ast.Call) -> bool:
        return all(self.visit(arg) for arg in node.args)


def _is_constant(expr: ast.Expr) -> bool:
    return _ConstantVisitor().visit(expr)


def _lower_bounded_tables(expr: ast.Expr, context: HogQLContext, scan: _SelectScan) -> set[int]:
    if isinstance(expr, ast.Or) or (isinstance(expr, ast.Call) and expr.name == "or"):
        branches = expr.exprs if isinstance(expr, ast.Or) else expr.args
        bounded_per_branch = [
            set().union(*(_lower_bounded_tables(conjunct, context, scan) for conjunct in top_level_conjuncts(branch)))
            for branch in branches
        ]
        return set.intersection(*bounded_per_branch) if bounded_per_branch else set()
    if isinstance(expr, ast.CompareOperation):
        bounded: set[int] = set()
        if expr.op in _LOWER_BOUND_OPS and _is_constant(expr.right):
            bounded |= _timestamp_tables(expr.left, context, scan)
        if expr.op in _FLIPPED_LOWER_BOUND_OPS and _is_constant(expr.left):
            bounded |= _timestamp_tables(expr.right, context, scan)
        return bounded
    if isinstance(expr, ast.BetweenExpr) and not expr.negated and _is_constant(expr.low):
        return _timestamp_tables(expr.expr, context, scan)
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
