from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import is_nondeterministic_function
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen


@frozen
class _Period:
    interval_function: str
    count: int


_DAY = _Period(interval_function="toIntervalDay", count=1)
_TIME_ZONE_SLACK = _Period(interval_function="toIntervalDay", count=2)
_PERIODS_BY_UNIT = {
    "second": _Period(interval_function="toIntervalSecond", count=1),
    "minute": _Period(interval_function="toIntervalMinute", count=1),
    "hour": _Period(interval_function="toIntervalHour", count=1),
    "day": _DAY,
    "week": _Period(interval_function="toIntervalDay", count=7),
    "month": _Period(interval_function="toIntervalMonth", count=1),
    "quarter": _Period(interval_function="toIntervalMonth", count=3),
    "year": _Period(interval_function="toIntervalMonth", count=12),
}
_TRUNCATING_FUNCTION_UNITS = {
    "todate": "day",
    "tostartofday": "day",
    "tostartofhour": "hour",
    "tostartofminute": "minute",
    "tostartofweek": "week",
    "tomonday": "week",
    "tostartofisoweek": "week",
    "tostartofmonth": "month",
    "tostartofquarter": "quarter",
    "tostartofyear": "year",
}
_DATE_TRUNC_FUNCTIONS = {"datetrunc", "date_trunc"}
_FLIPPED_OPS = {
    ast.CompareOperationOp.Gt: ast.CompareOperationOp.Lt,
    ast.CompareOperationOp.GtEq: ast.CompareOperationOp.LtEq,
    ast.CompareOperationOp.Lt: ast.CompareOperationOp.Gt,
    ast.CompareOperationOp.LtEq: ast.CompareOperationOp.GtEq,
    ast.CompareOperationOp.Eq: ast.CompareOperationOp.Eq,
}
_LOWER_BOUND_OPS = {ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Eq}
_UPPER_BOUND_OPS = {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Eq}


@frozen
class _TruncatedTimestamp:
    timestamp: ast.Field
    period: _Period
    returns_date: bool


class _NonConstantFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = True

    def visit_call(self, node: ast.Call) -> None:
        if is_nondeterministic_function(node.name):
            self.found = True
        super().visit_call(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.found = True

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.found = True


class TrinoEventsTimestampRangeAdder(TraversingVisitor):
    """Adds a range on the bare `events.timestamp` next to each WHERE filter that truncates it, so Trino can prune."""

    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)
        if node.where is not None:
            node.where = self._with_ranges(node.where)
        if node.prewhere is not None:
            node.prewhere = self._with_ranges(node.prewhere)

    def _with_ranges(self, predicate: ast.Expr) -> ast.Expr:
        conjuncts = predicate.exprs if isinstance(predicate, ast.And) else [predicate]
        ranges = [bound for conjunct in conjuncts for bound in self._implied_ranges(conjunct)]
        if not ranges:
            return predicate
        return ast.And(exprs=[*conjuncts, *ranges])

    def _implied_ranges(self, predicate: ast.Expr) -> list[ast.Expr]:
        if isinstance(predicate, ast.BetweenExpr) and not predicate.negated:
            truncated = self._truncated_timestamp(predicate.expr)
            if truncated is None or not self._is_time_constant(predicate.low, predicate.high):
                return []
            return [self._lower_bound(truncated, predicate.low), self._upper_bound(truncated, predicate.high)]
        if not isinstance(predicate, ast.CompareOperation) or predicate.op not in _FLIPPED_OPS:
            return []
        op, truncated, bound = predicate.op, self._truncated_timestamp(predicate.left), predicate.right
        if truncated is None:
            op, truncated, bound = _FLIPPED_OPS[op], self._truncated_timestamp(predicate.right), predicate.left
        if truncated is None or not self._is_time_constant(bound):
            return []
        ranges = []
        if op in _LOWER_BOUND_OPS:
            ranges.append(self._lower_bound(truncated, bound))
        if op in _UPPER_BOUND_OPS:
            ranges.append(self._upper_bound(truncated, bound))
        return ranges

    def _truncated_timestamp(self, expr: ast.Expr) -> _TruncatedTimestamp | None:
        if not isinstance(expr, ast.Call) or not expr.args:
            return None
        name = expr.name.lower()
        if name in _TRUNCATING_FUNCTION_UNITS:
            return self._events_timestamp(expr, expr.args[0], _TRUNCATING_FUNCTION_UNITS[name])
        if name in _DATE_TRUNC_FUNCTIONS and len(expr.args) >= 2:
            unit = expr.args[0]
            if isinstance(unit, ast.Constant) and isinstance(unit.value, str):
                return self._events_timestamp(expr, expr.args[1], unit.value.lower())
        return None

    def _events_timestamp(self, call: ast.Call, expr: ast.Expr, unit: str) -> _TruncatedTimestamp | None:
        period = _PERIODS_BY_UNIT.get(unit)
        while isinstance(expr, ast.Alias):
            expr = expr.expr
        if period is None or not isinstance(expr, ast.Field) or not isinstance(expr.type, ast.FieldType):
            return None
        if expr.type.name != "timestamp":
            return None
        table_type = expr.type.table_type
        while isinstance(table_type, ast.TableAliasType):
            table_type = table_type.table_type
        if not isinstance(table_type, ast.TableType) or not isinstance(table_type.table, EventsTable):
            return None
        returns_date = call.type is not None and isinstance(call.type.resolve_constant_type(self.context), ast.DateType)
        return _TruncatedTimestamp(timestamp=expr, period=period, returns_date=returns_date)

    def _is_time_constant(self, *exprs: ast.Expr) -> bool:
        for expr in exprs:
            finder = _NonConstantFinder()
            finder.visit(expr)
            if finder.found or expr.type is None:
                return False
            constant_type = expr.type.resolve_constant_type(self.context)
            is_date_string = isinstance(expr, ast.Constant) and isinstance(expr.value, str)
            if not is_date_string and not isinstance(constant_type, ast.DateType | ast.DateTimeType):
                return False
        return True

    def _lower_bound(self, truncated: _TruncatedTimestamp, bound: ast.Expr) -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=clone_expr(truncated.timestamp),
            right=ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Sub, left=_to_datetime(truncated, bound), right=_interval(_TIME_ZONE_SLACK)
            ),
        )

    def _upper_bound(self, truncated: _TruncatedTimestamp, bound: ast.Expr) -> ast.Expr:
        latest_bound = ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Add, left=_to_datetime(truncated, bound), right=_interval(_TIME_ZONE_SLACK)
        )
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=clone_expr(truncated.timestamp),
            right=ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Add, left=latest_bound, right=_interval(truncated.period)
            ),
        )


class _AliasDefinitionRemover(CloningVisitor):
    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


def _to_datetime(truncated: _TruncatedTimestamp, bound: ast.Expr) -> ast.Expr:
    bound = _AliasDefinitionRemover().visit(bound)
    if truncated.returns_date and isinstance(bound, ast.Constant):
        bound = ast.Call(name="toDate", args=[bound])
    return ast.Call(name="toDateTime", args=[bound])


def _interval(period: _Period) -> ast.Expr:
    return ast.Call(name=period.interval_function, args=[ast.Constant(value=period.count)])


def add_events_timestamp_ranges(node: ast.AST, context: HogQLContext) -> ast.AST:
    TrinoEventsTimestampRangeAdder(context).visit(node)
    return node
