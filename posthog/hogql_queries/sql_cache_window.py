from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Optional
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse
from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen


class SqlWindowClass(StrEnum):
    FIXED_PAST = "fixed_past"
    LIVE = "live"
    UP_TO_NOW_SHORT = "up_to_now_short"
    UP_TO_NOW_LONG = "up_to_now_long"
    NO_TIME_FILTER = "no_time_filter"
    UNCLASSIFIED = "unclassified"


API_SQL_WINDOW_CACHE_AGE_FLAG = "api-sql-window-cache-age"

SQL_WINDOW_MAX_AGE: dict[SqlWindowClass, timedelta] = {
    SqlWindowClass.FIXED_PAST: timedelta(hours=24),
    SqlWindowClass.LIVE: timedelta(minutes=5),
    SqlWindowClass.UP_TO_NOW_SHORT: timedelta(minutes=30),
    SqlWindowClass.UP_TO_NOW_LONG: timedelta(hours=1),
    SqlWindowClass.NO_TIME_FILTER: timedelta(minutes=5),
    SqlWindowClass.UNCLASSIFIED: timedelta(minutes=5),
}

LIVE_WINDOW_MAX_LENGTH = timedelta(hours=1)
SHORT_WINDOW_MAX_LENGTH = timedelta(days=1)

TIME_COLUMN_NAMES = frozenset({"timestamp", "time", "date", "day", "hour", "event_time", "event_date"})
TIME_COLUMN_SUFFIXES = ("timestamp", "_time", "_date", "_at")

_DATE_PREFIX_LENGTH = len("2026-01-01")
_NOW_FUNCTIONS = frozenset({"now", "now64", "current_timestamp", "today", "yesterday"})
_PASSTHROUGH_FUNCTIONS = frozenset(
    {
        "toDateTime",
        "toDateTime64",
        "toTimeZone",
        "assumeNotNull",
        "parseDateTimeBestEffort",
        "parseDateTime64BestEffort",
    }
)
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
_DATE_SHIFT_FUNCTIONS = {
    "dateSub": -1,
    "date_sub": -1,
    "timestamp_sub": -1,
    "dateAdd": 1,
    "date_add": 1,
    "timestamp_add": 1,
}
_LOWER_BOUND_OPS = frozenset({ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq})
_UPPER_BOUND_OPS = frozenset({ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq})
_FLIPPED_OPS = {
    ast.CompareOperationOp.Gt: ast.CompareOperationOp.Lt,
    ast.CompareOperationOp.GtEq: ast.CompareOperationOp.LtEq,
    ast.CompareOperationOp.Lt: ast.CompareOperationOp.Gt,
    ast.CompareOperationOp.LtEq: ast.CompareOperationOp.GtEq,
    ast.CompareOperationOp.Eq: ast.CompareOperationOp.Eq,
}


@frozen
class SqlTimeWindow:
    start: Optional[datetime]
    end: Optional[datetime]


class _Unclassifiable(Exception):
    pass


def _looks_like_date(value: str) -> bool:
    return (
        len(value) >= _DATE_PREFIX_LENGTH
        and value[:4].isdigit()
        and value[4] == "-"
        and value[5:7].isdigit()
        and value[7] == "-"
        and value[8:10].isdigit()
    )


def _unit_delta(unit: str, amount: int) -> relativedelta:
    return _UNIT_DELTAS[unit] * amount


def _int_constant(expr: ast.Expr) -> Optional[int]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    return None


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


def _is_filters_placeholder(expr: ast.Expr) -> bool:
    if not isinstance(expr, ast.Placeholder):
        return False
    if isinstance(expr.expr, ast.Field):
        return expr.expr.chain == ["filters"]
    return isinstance(expr.expr, ast.Call) and expr.expr.name == "filters"


class _SelectCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[ast.SelectQuery] = []
        self.cte_names: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        self.cte_names.update((node.ctes or {}).keys())
        super().visit_select_query(node)


class _TemporalFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_call(self, node: ast.Call) -> None:
        if node.name in _NOW_FUNCTIONS:
            self.found = True
        super().visit_call(node)

    def visit_constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, (datetime, date)) or (isinstance(node.value, str) and _looks_like_date(node.value)):
            self.found = True

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        self.found = True


class _FieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.fields: list[ast.Field] = []

    def visit_field(self, node: ast.Field) -> None:
        self.fields.append(node)


def _looks_temporal(expr: ast.Expr) -> bool:
    finder = _TemporalFinder()
    finder.visit(expr)
    return finder.found


def _time_column(expr: ast.Expr) -> Optional[str]:
    if _looks_temporal(expr):
        return None
    finder = _FieldFinder()
    finder.visit(expr)
    if len(finder.fields) != 1:
        return None
    chain = [str(part).lower() for part in finder.fields[0].chain]
    if "properties" in chain:
        return None
    name = chain[-1]
    if name in TIME_COLUMN_NAMES or name.endswith(TIME_COLUMN_SUFFIXES):
        return ".".join(chain)
    return None


class SqlWindowClassifier:
    def __init__(self, *, now: datetime, timezone: ZoneInfo, filters_window: Optional[SqlTimeWindow]) -> None:
        self._now = now.astimezone(timezone)
        self._timezone = timezone
        self._filters_window = filters_window
        self._start_of_today = _truncate(self._now, "day", timezone)

    def _constant_datetime(self, value: object) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=self._timezone)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=self._timezone)
        if isinstance(value, str) and _looks_like_date(value):
            try:
                parsed = isoparse(value)
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=self._timezone)
        return None

    def _evaluate_delta(self, expr: ast.Expr) -> Optional[relativedelta]:
        days = _int_constant(expr)
        if days is not None:
            return _unit_delta("day", days)
        if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
            unit = expr.name.removeprefix("toInterval").lower()
            amount = _int_constant(expr.args[0])
            if unit in _UNIT_DELTAS and amount is not None:
                return _unit_delta(unit, amount)
        return None

    def _evaluate_date_shift(self, sign: int, args: list[ast.Expr]) -> Optional[datetime]:
        if len(args) == 3 and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
            unit = args[0].value.lower().rstrip("s")
            amount = _int_constant(args[1])
            inner = self._evaluate_datetime(args[2])
            if unit in _UNIT_DELTAS and amount is not None and inner is not None:
                return inner + _unit_delta(unit, sign * amount)
            return None
        if len(args) == 2:
            inner = self._evaluate_datetime(args[0])
            delta = self._evaluate_delta(args[1])
            return inner + delta * sign if inner is not None and delta is not None else None
        return None

    def _evaluate_datetime(self, expr: ast.Expr) -> Optional[datetime]:
        if isinstance(expr, ast.Alias):
            return self._evaluate_datetime(expr.expr)
        if isinstance(expr, ast.Constant):
            return self._constant_datetime(expr.value)
        if isinstance(expr, ast.Placeholder):
            if self._filters_window is None:
                return None
            if expr.chain == ["filters", "dateRange", "from"]:
                return self._filters_window.start
            if expr.chain == ["filters", "dateRange", "to"]:
                return self._filters_window.end
            return None
        if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
            ast.ArithmeticOperationOp.Add,
            ast.ArithmeticOperationOp.Sub,
        ):
            sign = 1 if expr.op == ast.ArithmeticOperationOp.Add else -1
            left = self._evaluate_datetime(expr.left)
            if left is not None:
                delta = self._evaluate_delta(expr.right)
                return left + delta * sign if delta is not None else None
            if sign == 1:
                right = self._evaluate_datetime(expr.right)
                delta = self._evaluate_delta(expr.left)
                return right + delta if right is not None and delta is not None else None
            return None
        if not isinstance(expr, ast.Call):
            return None
        name = expr.name
        if name in ("now", "now64", "current_timestamp"):
            return self._now
        if name == "today":
            return self._start_of_today
        if name == "yesterday":
            return self._start_of_today - timedelta(days=1)
        if not expr.args:
            return None
        if name in _PASSTHROUGH_FUNCTIONS:
            return self._evaluate_datetime(expr.args[0])
        if name in _TRUNCATE_FUNCTIONS:
            inner = self._evaluate_datetime(expr.args[0])
            return _truncate(inner, _TRUNCATE_FUNCTIONS[name], self._timezone) if inner is not None else None
        if name in _SHIFT_FUNCTIONS and len(expr.args) == 2:
            sign, unit = _SHIFT_FUNCTIONS[name]
            inner = self._evaluate_datetime(expr.args[0])
            amount = _int_constant(expr.args[1])
            return inner + _unit_delta(unit, sign * amount) if inner is not None and amount is not None else None
        if name in _DATE_SHIFT_FUNCTIONS:
            return self._evaluate_date_shift(_DATE_SHIFT_FUNCTIONS[name], expr.args)
        return None

    def _window_from_compare(
        self, column_side: ast.Expr, op: ast.CompareOperationOp, value_side: ast.Expr
    ) -> Optional[tuple[str, SqlTimeWindow]]:
        column = _time_column(column_side)
        if column is None:
            return None
        value = self._evaluate_datetime(value_side)
        if value is None:
            return None
        if op in _LOWER_BOUND_OPS:
            return column, SqlTimeWindow(start=value, end=None)
        if op in _UPPER_BOUND_OPS:
            return column, SqlTimeWindow(start=None, end=value)
        unit = _TRUNCATE_FUNCTIONS.get(column_side.name) if isinstance(column_side, ast.Call) else None
        return column, SqlTimeWindow(start=value, end=value + _unit_delta(unit, 1) if unit else value)

    def _window_from_conjunct(self, conjunct: ast.Expr) -> Optional[tuple[str, SqlTimeWindow]]:
        if _is_filters_placeholder(conjunct):
            if self._filters_window is None:
                return None
            return "{filters}", self._filters_window
        if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _FLIPPED_OPS:
            bound = self._window_from_compare(conjunct.left, conjunct.op, conjunct.right)
            if bound is None:
                bound = self._window_from_compare(conjunct.right, _FLIPPED_OPS[conjunct.op], conjunct.left)
            if bound is not None:
                return bound
        if isinstance(conjunct, ast.BetweenExpr) and not conjunct.negated:
            column = _time_column(conjunct.expr)
            low = self._evaluate_datetime(conjunct.low)
            high = self._evaluate_datetime(conjunct.high)
            if column is not None and low is not None and high is not None:
                return column, SqlTimeWindow(start=low, end=high)
        if _looks_temporal(conjunct):
            raise _Unclassifiable()
        return None

    def _conjuncts(self, expr: Optional[ast.Expr]) -> list[ast.Expr]:
        if expr is None:
            return []
        if isinstance(expr, ast.And):
            return [conjunct for inner in expr.exprs for conjunct in self._conjuncts(inner)]
        return [expr]

    def _reads_base_table(self, select: ast.SelectQuery, cte_names: set[str]) -> bool:
        join = select.select_from
        while join is not None:
            if isinstance(join.table, ast.Field) and not (
                len(join.table.chain) == 1 and join.table.chain[0] in cte_names
            ):
                return True
            join = join.next_join
        return False

    def _class_for_window(self, window: SqlTimeWindow) -> SqlWindowClass:
        if window.end is not None and window.end <= self._start_of_today:
            return SqlWindowClass.FIXED_PAST
        if window.start is None:
            return SqlWindowClass.NO_TIME_FILTER
        length = self._now - window.start
        if length <= LIVE_WINDOW_MAX_LENGTH:
            return SqlWindowClass.LIVE
        if length <= SHORT_WINDOW_MAX_LENGTH:
            return SqlWindowClass.UP_TO_NOW_SHORT
        return SqlWindowClass.UP_TO_NOW_LONG

    def _classify_select(self, select: ast.SelectQuery, cte_names: set[str]) -> Optional[SqlWindowClass]:
        starts: dict[str, list[datetime]] = {}
        ends: dict[str, list[datetime]] = {}
        for conjunct in self._conjuncts(select.where) + self._conjuncts(select.prewhere):
            bound = self._window_from_conjunct(conjunct)
            if bound is None:
                continue
            column, window = bound
            starts.setdefault(column, [])
            ends.setdefault(column, [])
            if window.start is not None:
                starts[column].append(window.start)
            if window.end is not None:
                ends[column].append(window.end)
        if not starts:
            return SqlWindowClass.NO_TIME_FILTER if self._reads_base_table(select, cte_names) else None
        return min(
            (
                self._class_for_window(
                    SqlTimeWindow(
                        start=max(starts[column]) if starts[column] else None,
                        end=min(ends[column]) if ends[column] else None,
                    )
                )
                for column in starts
            ),
            key=lambda window_class: SQL_WINDOW_MAX_AGE[window_class],
        )

    def classify(self, query: ast.SelectQuery | ast.SelectSetQuery) -> SqlWindowClass:
        collector = _SelectCollector()
        collector.visit(query)
        try:
            classes = [
                window_class
                for select in collector.selects
                if (window_class := self._classify_select(select, collector.cte_names)) is not None
            ]
        except _Unclassifiable:
            return SqlWindowClass.UNCLASSIFIED
        if not classes:
            return SqlWindowClass.NO_TIME_FILTER
        return min(classes, key=lambda window_class: SQL_WINDOW_MAX_AGE[window_class])
