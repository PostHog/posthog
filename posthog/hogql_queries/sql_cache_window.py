from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Optional
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse
from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.database.models import DatabaseField, ExpressionField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.functions.clickhouse.datetime import DATE_GENERATOR_FUNCTIONS
from posthog.hogql.functions.mapping import find_hogql_function
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen


class SqlWindowClass(StrEnum):
    FIXED_PAST = "fixed_past"
    LIVE = "live"
    UP_TO_NOW_SHORT = "up_to_now_short"
    UP_TO_NOW_LONG = "up_to_now_long"


API_SQL_WINDOW_CACHE_AGE_FLAG = "api-sql-window-cache-age"

SQL_WINDOW_MAX_AGE: dict[SqlWindowClass, timedelta] = {
    SqlWindowClass.FIXED_PAST: timedelta(hours=24),
    SqlWindowClass.LIVE: timedelta(minutes=5),
    SqlWindowClass.UP_TO_NOW_SHORT: timedelta(minutes=30),
    SqlWindowClass.UP_TO_NOW_LONG: timedelta(hours=1),
}

LIVE_WINDOW_MAX_LENGTH = timedelta(hours=1)
SHORT_WINDOW_MAX_LENGTH = timedelta(days=1)
FIXED_PAST_SETTLE_TIME = timedelta(hours=1)

_DATE_PREFIX_LENGTH = len("2026-01-01")
_TIMESTAMP_COLUMN = "timestamp"
_TIMESTAMP_WRAPPERS = frozenset({"toDateTime", "toDateTime64", "parseDateTimeBestEffort", "parseDateTime64BestEffort"})
_DATE_RESULT_FUNCTIONS = frozenset({"toDate"})
_TRUNCATE_FUNCTIONS = {
    "toDate": "day",
    "toStartOfDay": "day",
    "toStartOfHour": "hour",
    "toStartOfMinute": "minute",
    "toMonday": "week",
    "toStartOfWeek": "week",
    "toStartOfMonth": "month",
    "toStartOfQuarter": "quarter",
    "toStartOfYear": "year",
}
_UNIT_DELTAS = {
    "second": relativedelta(seconds=1),
    "minute": relativedelta(minutes=1),
    "hour": relativedelta(hours=1),
    "day": relativedelta(days=1),
    "week": relativedelta(weeks=1),
    "month": relativedelta(months=1),
    "quarter": relativedelta(months=3),
    "year": relativedelta(years=1),
}
_SHIFT_FUNCTIONS = {
    f"{verb}{unit.capitalize()}s": (sign, unit)
    for verb, sign in (("subtract", -1), ("add", 1))
    for unit in _UNIT_DELTAS
}
_DATE_SHIFT_FUNCTIONS = {"dateSub": -1, "date_sub": -1, "dateAdd": 1, "date_add": 1}
_LOWER_BOUND_OPS = frozenset({ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq})
_UPPER_BOUND_OPS = frozenset({ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq})
_TRUNCATION_SHIFTED_OPS = frozenset({ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Gt})
_FLIPPED_OPS = {
    ast.CompareOperationOp.Gt: ast.CompareOperationOp.Lt,
    ast.CompareOperationOp.GtEq: ast.CompareOperationOp.LtEq,
    ast.CompareOperationOp.Lt: ast.CompareOperationOp.Gt,
    ast.CompareOperationOp.LtEq: ast.CompareOperationOp.GtEq,
    ast.CompareOperationOp.Eq: ast.CompareOperationOp.Eq,
}


@frozen
class SqlFreshness:
    window: SqlWindowClass
    fresh_until: datetime


@frozen
class _Value:
    at: datetime
    is_date: bool


class _Unqualified(Exception):
    pass


def _clock_name(call: ast.Call) -> Optional[str]:
    meta = find_hogql_function(call.name)
    if meta is None or not any(meta is generator for generator in DATE_GENERATOR_FUNCTIONS.values()):
        return None
    return meta.clickhouse_name


def _events_table_type(table_type: Any) -> Optional[ast.TableType]:
    if isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    if isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable):
        return table_type
    return None


def _is_subquery_type(table_type: Any) -> bool:
    return isinstance(
        table_type, ast.SelectQueryType | ast.SelectSetQueryType | ast.SelectQueryAliasType | ast.CTETableType
    )


def _is_immutable_field_type(field_type: Any) -> bool:
    if isinstance(field_type, ast.FieldAliasType):
        return True
    if isinstance(field_type, ast.PropertyType):
        return _is_immutable_field_type(field_type.field_type)
    if not isinstance(field_type, ast.FieldType):
        return False
    if _is_subquery_type(field_type.table_type):
        return True
    events = _events_table_type(field_type.table_type)
    if events is None:
        return False
    database_field = events.table.fields.get(field_type.name)
    return isinstance(database_field, DatabaseField) and not isinstance(database_field, ExpressionField)


def _unwrap_alias(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


def _is_events_timestamp(expr: ast.Expr) -> bool:
    expr = _unwrap_alias(expr)
    field_type = expr.type if isinstance(expr, ast.Field) else None
    return (
        isinstance(field_type, ast.FieldType)
        and field_type.name == _TIMESTAMP_COLUMN
        and _events_table_type(field_type.table_type) is not None
    )


def _int_constant(expr: ast.Expr) -> Optional[int]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    return None


def _string_constant(expr: ast.Expr) -> Optional[str]:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def _looks_like_date(value: str) -> bool:
    return (
        len(value) >= _DATE_PREFIX_LENGTH
        and value[:4].isdigit()
        and value[4] == "-"
        and value[5:7].isdigit()
        and value[7] == "-"
        and value[8:10].isdigit()
    )


def _truncate(value: datetime, unit: str, timezone: ZoneInfo) -> datetime:
    local = value.astimezone(timezone)
    if unit == "minute":
        return local.replace(second=0, microsecond=0)
    if unit == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "day":
        return day
    if unit == "week":
        return day - timedelta(days=day.weekday())
    if unit == "month":
        return day.replace(day=1)
    if unit == "quarter":
        return day.replace(month=3 * ((day.month - 1) // 3) + 1, day=1)
    return day.replace(month=1, day=1)


class _TimestampFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if _is_events_timestamp(node):
            self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass


def _mentions_events_timestamp(expr: ast.Expr) -> bool:
    finder = _TimestampFinder()
    finder.visit(expr)
    return finder.found


class _QueryScan(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[ast.SelectQuery] = []
        self.clock_calls: set[int] = set()
        self.mutable_fields = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        super().visit_select_query(node)

    def visit_field(self, node: ast.Field) -> None:
        if not isinstance(node.type, ast.BaseTableType) and not _is_immutable_field_type(node.type):
            self.mutable_fields = True

    def visit_call(self, node: ast.Call) -> None:
        if _clock_name(node) is not None:
            self.clock_calls.add(id(node))
        super().visit_call(node)


class SqlFreshnessClassifier:
    def __init__(self, *, now: datetime, timezone: ZoneInfo, relative_date_range: bool) -> None:
        self._now = now.astimezone(timezone)
        self._timezone = timezone
        self._relative_date_range = relative_date_range
        self._start_of_today = _truncate(self._now, "day", timezone)
        self._consumed_clock_calls: set[int] = set()
        self._reads_now = False

    def _parse_string(self, value: str, timezone: ZoneInfo) -> Optional[_Value]:
        try:
            parsed = isoparse(value)
        except ValueError:
            return None
        return _Value(
            at=parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone), is_date=len(value) == _DATE_PREFIX_LENGTH
        )

    def _constant_value(self, value: object) -> Optional[_Value]:
        if isinstance(value, datetime):
            return _Value(at=value if value.tzinfo else value.replace(tzinfo=self._timezone), is_date=False)
        if isinstance(value, date):
            return _Value(at=datetime(value.year, value.month, value.day, tzinfo=self._timezone), is_date=True)
        if isinstance(value, str) and _looks_like_date(value):
            return self._parse_string(value, self._timezone)
        return None

    def _evaluate_delta(self, expr: ast.Expr, base: _Value) -> Optional[relativedelta]:
        amount = _int_constant(expr)
        if amount is not None:
            return _UNIT_DELTAS["day" if base.is_date else "second"] * amount
        if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
            unit = expr.name.removeprefix("toInterval").lower()
            interval_amount = _int_constant(expr.args[0])
            if unit in _UNIT_DELTAS and interval_amount is not None:
                return _UNIT_DELTAS[unit] * interval_amount
        return None

    def _evaluate_wrapper(self, call: ast.Call) -> Optional[_Value]:
        timezone_arg = _string_constant(call.args[-1]) if len(call.args) > 1 else None
        literal = _string_constant(call.args[0])
        if literal is not None and _looks_like_date(literal):
            try:
                timezone = ZoneInfo(timezone_arg) if timezone_arg else self._timezone
            except (KeyError, ValueError):
                return None
            value = self._parse_string(literal, timezone)
            return _Value(at=value.at, is_date=False) if value else None
        if timezone_arg is not None:
            return None
        inner = self._evaluate(call.args[0])
        return _Value(at=inner.at, is_date=False) if inner else None

    def _evaluate_call(self, call: ast.Call) -> Optional[_Value]:
        clock = _clock_name(call)
        if clock is not None:
            if call.args:
                return None
            self._consumed_clock_calls.add(id(call))
            if clock in ("now64", "now"):
                self._reads_now = True
                return _Value(at=self._now, is_date=False)
            if clock == "today":
                return _Value(at=self._start_of_today, is_date=True)
            if clock == "yesterday":
                return _Value(at=self._start_of_today - timedelta(days=1), is_date=True)
            return None
        if not call.args:
            return None
        if call.name in _TIMESTAMP_WRAPPERS:
            return self._evaluate_wrapper(call)
        if call.name in _TRUNCATE_FUNCTIONS and len(call.args) == 1:
            inner = self._evaluate(call.args[0])
            if inner is None:
                return None
            truncated = _truncate(inner.at, _TRUNCATE_FUNCTIONS[call.name], self._timezone)
            return _Value(at=truncated, is_date=call.name in _DATE_RESULT_FUNCTIONS)
        if call.name in _SHIFT_FUNCTIONS and len(call.args) == 2:
            sign, unit = _SHIFT_FUNCTIONS[call.name]
            inner = self._evaluate(call.args[0])
            amount = _int_constant(call.args[1])
            if inner is None or amount is None:
                return None
            return _Value(at=inner.at + _UNIT_DELTAS[unit] * (sign * amount), is_date=inner.is_date)
        if call.name in _DATE_SHIFT_FUNCTIONS and len(call.args) == 3:
            unit = (_string_constant(call.args[0]) or "").lower().rstrip("s")
            amount = _int_constant(call.args[1])
            inner = self._evaluate(call.args[2])
            if unit not in _UNIT_DELTAS or amount is None or inner is None:
                return None
            sign = _DATE_SHIFT_FUNCTIONS[call.name]
            return _Value(at=inner.at + _UNIT_DELTAS[unit] * (sign * amount), is_date=inner.is_date)
        return None

    def _evaluate(self, expr: ast.Expr) -> Optional[_Value]:
        expr = _unwrap_alias(expr)
        if isinstance(expr, ast.Constant):
            return self._constant_value(expr.value)
        if isinstance(expr, ast.Call):
            return self._evaluate_call(expr)
        if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
            ast.ArithmeticOperationOp.Add,
            ast.ArithmeticOperationOp.Sub,
        ):
            base = self._evaluate(expr.left)
            if base is None:
                return None
            delta = self._evaluate_delta(expr.right, base)
            if delta is None:
                return None
            sign = 1 if expr.op == ast.ArithmeticOperationOp.Add else -1
            return _Value(at=base.at + delta * sign, is_date=base.is_date)
        return None

    def _column_unit(self, expr: ast.Expr) -> tuple[bool, Optional[str]]:
        expr = _unwrap_alias(expr)
        if _is_events_timestamp(expr):
            return True, None
        if (
            isinstance(expr, ast.Call)
            and expr.name in _TRUNCATE_FUNCTIONS
            and len(expr.args) == 1
            and _is_events_timestamp(expr.args[0])
        ):
            return True, _TRUNCATE_FUNCTIONS[expr.name]
        return False, None

    def _bound(
        self, column: ast.Expr, op: ast.CompareOperationOp, value_expr: ast.Expr
    ) -> Optional[tuple[Optional[datetime], Optional[datetime]]]:
        is_column, unit = self._column_unit(column)
        if not is_column:
            return None
        value = self._evaluate(value_expr)
        if value is None:
            raise _Unqualified()
        step = _UNIT_DELTAS[unit] if unit else relativedelta()
        if op in _LOWER_BOUND_OPS:
            return (value.at + step if unit and op in _TRUNCATION_SHIFTED_OPS else value.at), None
        if op in _UPPER_BOUND_OPS:
            return None, (value.at + step if unit and op in _TRUNCATION_SHIFTED_OPS else value.at)
        return value.at, value.at + step

    def _bounds_from_conjunct(self, conjunct: ast.Expr) -> tuple[Optional[datetime], Optional[datetime]]:
        if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _FLIPPED_OPS:
            bound = self._bound(conjunct.left, conjunct.op, conjunct.right)
            if bound is None:
                bound = self._bound(conjunct.right, _FLIPPED_OPS[conjunct.op], conjunct.left)
            if bound is not None:
                return bound
        if isinstance(conjunct, ast.BetweenExpr) and not conjunct.negated:
            is_column, unit = self._column_unit(conjunct.expr)
            if is_column:
                low = self._evaluate(conjunct.low)
                high = self._evaluate(conjunct.high)
                if low is None or high is None:
                    raise _Unqualified()
                return low.at, high.at + (_UNIT_DELTAS[unit] if unit else relativedelta())
        raise _Unqualified()

    def _conjuncts(self, expr: Optional[ast.Expr]) -> list[ast.Expr]:
        if expr is None:
            return []
        if isinstance(expr, ast.And):
            return [conjunct for inner in expr.exprs for conjunct in self._conjuncts(inner)]
        return [expr]

    def _reads_events_directly(self, select: ast.SelectQuery) -> bool:
        join = select.select_from
        if join is None:
            return False
        if join.next_join is not None:
            raise _Unqualified()
        if _events_table_type(join.type) is not None:
            return True
        if _is_subquery_type(join.type):
            return False
        raise _Unqualified()

    def _select_window(self, select: ast.SelectQuery) -> Optional[tuple[datetime, Optional[datetime]]]:
        if not self._reads_events_directly(select):
            return None
        starts: list[datetime] = []
        ends: list[datetime] = []
        for conjunct in self._conjuncts(select.where) + self._conjuncts(select.prewhere):
            if not _mentions_events_timestamp(conjunct):
                continue
            start, end = self._bounds_from_conjunct(conjunct)
            if start is not None:
                starts.append(start)
            if end is not None:
                ends.append(end)
        if not starts:
            raise _Unqualified()
        return max(starts), min(ends) if ends else None

    def _freshness_for(self, start: datetime, end: Optional[datetime], clock_derived: bool) -> SqlFreshness:
        if end is not None and end <= self._start_of_today and end <= self._now - FIXED_PAST_SETTLE_TIME:
            fresh_until = self._now + SQL_WINDOW_MAX_AGE[SqlWindowClass.FIXED_PAST]
            if clock_derived:
                fresh_until = min(fresh_until, self._start_of_today + timedelta(days=1))
            if self._reads_now:
                fresh_until = min(fresh_until, self._now + SQL_WINDOW_MAX_AGE[SqlWindowClass.UP_TO_NOW_LONG])
            return SqlFreshness(window=SqlWindowClass.FIXED_PAST, fresh_until=fresh_until.astimezone(UTC))
        length = self._now - start
        if length <= LIVE_WINDOW_MAX_LENGTH:
            window = SqlWindowClass.LIVE
        elif length <= SHORT_WINDOW_MAX_LENGTH:
            window = SqlWindowClass.UP_TO_NOW_SHORT
        else:
            window = SqlWindowClass.UP_TO_NOW_LONG
        return SqlFreshness(window=window, fresh_until=(self._now + SQL_WINDOW_MAX_AGE[window]).astimezone(UTC))

    def classify(self, resolved_query: ast.SelectQuery | ast.SelectSetQuery) -> Optional[SqlFreshness]:
        scan = _QueryScan()
        scan.visit(resolved_query)
        if scan.mutable_fields:
            return None
        self._consumed_clock_calls = set()
        self._reads_now = False
        try:
            windows = [window for select in scan.selects if (window := self._select_window(select)) is not None]
        except _Unqualified:
            return None
        if not windows or scan.clock_calls - self._consumed_clock_calls:
            return None
        clock_derived = self._relative_date_range or bool(self._consumed_clock_calls)
        return min(
            (self._freshness_for(start, end, clock_derived) for start, end in windows),
            key=lambda freshness: freshness.fresh_until,
        )


def freshness_record(freshness: SqlFreshness) -> dict[str, str]:
    return {"window": freshness.window.value, "fresh_until": freshness.fresh_until.astimezone(UTC).isoformat()}


def freshness_from_record(record: Any) -> Optional[SqlFreshness]:
    try:
        return SqlFreshness(window=SqlWindowClass(record["window"]), fresh_until=isoparse(record["fresh_until"]))
    except (KeyError, TypeError, ValueError):
        return None
