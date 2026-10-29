import dataclasses
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse
from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.database.models import DatabaseField, ExpressionField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.functions.clickhouse.datetime import DATE_GENERATOR_FUNCTIONS
from posthog.hogql.functions.mapping import find_hogql_function
from posthog.hogql.transforms.order_by_pushdown import unwrap_alias
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.interval_specs import INTERVAL_SPECS, PERIOD_MAP


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

_MONDAY = 1
_DATE_PREFIX_LENGTH = len("2026-01-01")
_TIMESTAMP_COLUMN = "timestamp"
_TIMESTAMP_WRAPPERS = frozenset({"toDateTime", "toDateTime64", "parseDateTimeBestEffort", "parseDateTime64BestEffort"})
_TRUNCATE_FUNCTIONS = {spec.trunc_func: unit for unit, spec in INTERVAL_SPECS.items() if spec.trunc_func} | {
    "toDate": "day",
    "toMonday": "week",
}
_SHIFT_FUNCTIONS = {
    f"{verb}{unit.capitalize()}s": (sign, unit) for verb, sign in (("subtract", -1), ("add", 1)) for unit in PERIOD_MAP
}
_DATE_SHIFT_FUNCTIONS = {"dateSub": -1, "date_sub": -1, "dateAdd": 1, "date_add": 1}
_CLOCK_FUNCTIONS = {id(meta): meta.clickhouse_name for meta in DATE_GENERATOR_FUNCTIONS.values()}
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
    utc_day: bool = False


class _Unqualified(Exception):
    pass


def _clock_name(call: ast.Call) -> Optional[str]:
    meta = find_hogql_function(call.name)
    return _CLOCK_FUNCTIONS.get(id(meta)) if meta is not None else None


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


def _is_events_timestamp(expr: ast.Expr) -> bool:
    expr = unwrap_alias(expr)
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


def _parse_string(value: str, timezone: tzinfo) -> Optional[_Value]:
    try:
        parsed = isoparse(value)
    except ValueError:
        return None
    return _Value(
        at=parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone), is_date=len(value) == _DATE_PREFIX_LENGTH
    )


def _start_of_day(value: datetime, timezone: tzinfo) -> datetime:
    return INTERVAL_SPECS["day"].align(value.astimezone(timezone), None)


def _period(unit: str, amount: int = 1) -> Union[timedelta, relativedelta]:
    return PERIOD_MAP[unit] * amount


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
    def __init__(
        self, *, now: datetime, timezone: tzinfo, week_start_day: Optional[int], relative_date_range: bool
    ) -> None:
        self._now = now.astimezone(timezone)
        self._timezone = timezone
        self._week_start_day = week_start_day
        self._relative_date_range = relative_date_range
        self._start_of_today = _start_of_day(self._now, timezone)
        self._start_of_utc_today = _start_of_day(self._now, UTC)
        self._consumed_clock_calls: set[int] = set()
        self._reads_now = False

    def _truncate(self, value: datetime, function: str) -> datetime:
        week_start_day = _MONDAY if function == "toMonday" else self._week_start_day
        return INTERVAL_SPECS[_TRUNCATE_FUNCTIONS[function]].align(value.astimezone(self._timezone), week_start_day)

    def _constant_value(self, value: object) -> Optional[_Value]:
        if isinstance(value, datetime):
            return _Value(at=value if value.tzinfo else value.replace(tzinfo=self._timezone), is_date=False)
        if isinstance(value, date):
            return _Value(at=datetime(value.year, value.month, value.day, tzinfo=self._timezone), is_date=True)
        if isinstance(value, str) and _looks_like_date(value):
            return _parse_string(value, self._timezone)
        return None

    def _evaluate_delta(self, expr: ast.Expr, base: _Value) -> Optional[Union[timedelta, relativedelta]]:
        amount = _int_constant(expr)
        if amount is not None:
            return _period("day" if base.is_date else "second", amount)
        if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
            unit = expr.name.removeprefix("toInterval").lower()
            interval_amount = _int_constant(expr.args[0])
            if unit in PERIOD_MAP and interval_amount is not None:
                return _period(unit, interval_amount)
        return None

    def _evaluate_wrapper(self, call: ast.Call) -> Optional[_Value]:
        timezone_arg = _string_constant(call.args[-1]) if len(call.args) > 1 else None
        literal = _string_constant(call.args[0])
        if literal is not None and _looks_like_date(literal):
            try:
                timezone = ZoneInfo(timezone_arg) if timezone_arg else self._timezone
            except (KeyError, ValueError):
                return None
            value = _parse_string(literal, timezone)
            return dataclasses.replace(value, is_date=False) if value else None
        if timezone_arg is not None:
            return None
        inner = self._evaluate(call.args[0])
        return dataclasses.replace(inner, is_date=False) if inner else None

    def _evaluate_shift(self, call: ast.Call) -> Optional[_Value]:
        if call.name in _SHIFT_FUNCTIONS and len(call.args) == 2:
            sign, unit = _SHIFT_FUNCTIONS[call.name]
            inner, amount = self._evaluate(call.args[0]), _int_constant(call.args[1])
        elif call.name in _DATE_SHIFT_FUNCTIONS and len(call.args) == 3:
            sign, unit = _DATE_SHIFT_FUNCTIONS[call.name], (_string_constant(call.args[0]) or "").lower().rstrip("s")
            inner, amount = self._evaluate(call.args[2]), _int_constant(call.args[1])
        else:
            return None
        if unit not in PERIOD_MAP or inner is None or amount is None:
            return None
        return dataclasses.replace(inner, at=inner.at + _period(unit, sign * amount))

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
                return _Value(at=self._start_of_utc_today, is_date=True, utc_day=True)
            if clock == "yesterday":
                return _Value(at=self._start_of_utc_today - timedelta(days=1), is_date=True, utc_day=True)
            return None
        if not call.args:
            return None
        if call.name in _TIMESTAMP_WRAPPERS:
            return self._evaluate_wrapper(call)
        if call.name in _TRUNCATE_FUNCTIONS and len(call.args) == 1:
            inner = self._evaluate(call.args[0])
            if inner is None or inner.utc_day:
                return None
            return _Value(at=self._truncate(inner.at, call.name), is_date=call.name == "toDate")
        return self._evaluate_shift(call)

    def _evaluate(self, expr: ast.Expr) -> Optional[_Value]:
        expr = unwrap_alias(expr)
        if isinstance(expr, ast.Constant):
            return self._constant_value(expr.value)
        if isinstance(expr, ast.Call):
            return self._evaluate_call(expr)
        if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
            ast.ArithmeticOperationOp.Add,
            ast.ArithmeticOperationOp.Sub,
        ):
            base = self._evaluate(expr.left)
            delta = self._evaluate_delta(expr.right, base) if base is not None else None
            if base is None or delta is None:
                return None
            return dataclasses.replace(
                base, at=base.at + delta if expr.op == ast.ArithmeticOperationOp.Add else base.at - delta
            )
        return None

    def _column_unit(self, expr: ast.Expr) -> tuple[bool, Optional[str]]:
        expr = unwrap_alias(expr)
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

    def _anchor(self, value: _Value, unit: Optional[str]) -> datetime:
        if not value.utc_day or unit is None:
            return value.at
        day = value.at.astimezone(UTC).date()
        return datetime(day.year, day.month, day.day, tzinfo=self._timezone)

    def _bound(
        self, column: ast.Expr, op: ast.CompareOperationOp, value_expr: ast.Expr
    ) -> Optional[tuple[Optional[datetime], Optional[datetime]]]:
        is_column, unit = self._column_unit(column)
        if not is_column:
            return None
        value = self._evaluate(value_expr)
        if value is None:
            raise _Unqualified()
        at = self._anchor(value, unit)
        step = _period(unit) if unit else timedelta()
        if op == ast.CompareOperationOp.Eq:
            return at, at + step
        edge = at + step if op in _TRUNCATION_SHIFTED_OPS else at
        return (edge, None) if op in _LOWER_BOUND_OPS else (None, edge)

    def _bounds_from_conjunct(self, conjunct: ast.Expr) -> tuple[Optional[datetime], Optional[datetime]]:
        if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _FLIPPED_OPS:
            bound = self._bound(conjunct.left, conjunct.op, conjunct.right)
            if bound is None:
                bound = self._bound(conjunct.right, _FLIPPED_OPS[conjunct.op], conjunct.left)
            if bound is not None:
                return bound
        if isinstance(conjunct, ast.BetweenExpr) and not conjunct.negated:
            low = self._bound(conjunct.expr, ast.CompareOperationOp.GtEq, conjunct.low)
            high = self._bound(conjunct.expr, ast.CompareOperationOp.LtEq, conjunct.high)
            if low is not None and high is not None:
                return low[0], high[1]
        raise _Unqualified()

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
        for clause in (select.where, select.prewhere):
            for conjunct in top_level_conjuncts(clause) if clause is not None else []:
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

    def _freshness_for(self, start: datetime, end: Optional[datetime]) -> SqlFreshness:
        if end is not None and end <= self._start_of_today and end <= self._now - FIXED_PAST_SETTLE_TIME:
            caps = [self._now + SQL_WINDOW_MAX_AGE[SqlWindowClass.FIXED_PAST]]
            if self._relative_date_range or self._consumed_clock_calls:
                caps += [self._start_of_today + timedelta(days=1), self._start_of_utc_today + timedelta(days=1)]
            if self._reads_now:
                caps.append(self._now + SQL_WINDOW_MAX_AGE[SqlWindowClass.UP_TO_NOW_LONG])
            return SqlFreshness(window=SqlWindowClass.FIXED_PAST, fresh_until=min(caps).astimezone(UTC))
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
        try:
            windows = [window for select in scan.selects if (window := self._select_window(select)) is not None]
        except _Unqualified:
            return None
        if not windows or scan.clock_calls - self._consumed_clock_calls:
            return None
        return min((self._freshness_for(start, end) for start, end in windows), key=lambda f: f.fresh_until)


def freshness_record(freshness: SqlFreshness) -> dict[str, str]:
    return {"window": freshness.window.value, "fresh_until": freshness.fresh_until.isoformat()}


def freshness_from_record(record: Any) -> Optional[SqlFreshness]:
    try:
        return SqlFreshness(window=SqlWindowClass(record["window"]), fresh_until=isoparse(record["fresh_until"]))
    except (KeyError, TypeError, ValueError):
        return None
