from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


# Cache policy. Every number that decides how long an API key SQL result stays fresh lives in this block.
API_SQL_WINDOW_CACHE_AGE_FLAG = "api-sql-window-cache-age"

# How long a result of each class stays fresh. LIVE, NO_TIME_FILTER and UNCLASSIFIED have no entry:
# they keep the runner's default staleness policy.
SQL_WINDOW_MAX_AGE: dict[SqlWindowClass, timedelta] = {
    SqlWindowClass.FIXED_PAST: timedelta(hours=24),
    SqlWindowClass.UP_TO_NOW_SHORT: timedelta(minutes=30),
    SqlWindowClass.UP_TO_NOW_LONG: timedelta(hours=1),
}
SQL_WINDOW_STRICTNESS = (
    SqlWindowClass.UNCLASSIFIED,
    SqlWindowClass.NO_TIME_FILTER,
    SqlWindowClass.LIVE,
    SqlWindowClass.UP_TO_NOW_SHORT,
    SqlWindowClass.UP_TO_NOW_LONG,
    SqlWindowClass.FIXED_PAST,
)

# A window counts as past only when it ended this long before the result was cached, so late events still land in it.
SQL_WINDOW_SETTLE_BUFFER = timedelta(hours=1)

# Up to now, a window of at most LIVE_WINDOW_MAX_LENGTH is LIVE, and one of at most SHORT_WINDOW_MAX_LENGTH is SHORT.
LIVE_WINDOW_MAX_LENGTH = timedelta(hours=1)
SHORT_WINDOW_MAX_LENGTH = timedelta(days=1)

# Only rows of these tables never change after they are written, so only they can have a fixed past.
APPEND_ONLY_TABLES = frozenset({"events"})

# A field that starts with one of these names (after the table alias) makes HogQL join the events to rows that change
# later, such as person or group properties. A query that reads one never gets a long age.
MUTABLE_JOIN_ROOTS = frozenset(
    {"person", "pdi", "person_id", "session", "override", "group_0", "group_1", "group_2", "group_3", "group_4"}
)
MUTABLE_JOIN_ROOT_PREFIXES = ("$group_",)

TIME_COLUMN_NAMES = frozenset({"timestamp", "time", "date", "day", "hour", "event_time", "event_date"})
TIME_COLUMN_SUFFIXES = ("timestamp", "_time", "_date", "_at")


_STRICTNESS_RANK = {window_class: rank for rank, window_class in enumerate(SQL_WINDOW_STRICTNESS)}
_DATE_PREFIX_LENGTH = len("2026-01-01")
_NOW_FUNCTIONS = frozenset({"now", "now64", "current_timestamp", "today", "yesterday"})
# ClickHouse evaluates today() and yesterday() in the server time zone, whatever the project time zone is.
_SERVER_TIMEZONE = ZoneInfo("UTC")
# toStartOfWeek is left out because its first weekday follows the project setting.
_TRUNCATE_FUNCTIONS = {
    "toDate": "day",
    "toStartOfDay": "day",
    "toStartOfHour": "hour",
    "toStartOfMinute": "minute",
    "toMonday": "week",
    "toStartOfMonth": "month",
    "toStartOfQuarter": "quarter",
    "toStartOfYear": "year",
}
_DATE_VALUED_FUNCTIONS = frozenset(
    {"today", "yesterday", "toDate", "toMonday", "toStartOfMonth", "toStartOfQuarter", "toStartOfYear"}
)
_DATETIME_VALUED_FUNCTIONS = frozenset(
    {
        "now",
        "now64",
        "current_timestamp",
        "toDateTime",
        "toDateTime64",
        "toStartOfDay",
        "toStartOfHour",
        "toStartOfMinute",
        "parseDateTimeBestEffort",
        "parseDateTime64BestEffort",
    }
)
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
_FILTERS_TIMESTAMP_KEY = "timestamp"


@frozen
class SqlTimeWindow:
    start: Optional[datetime]
    end: Optional[datetime]
    end_inclusive: bool = False
    start_absolute: bool = False
    end_absolute: bool = False


@frozen
class SqlWindowClassification:
    window_class: SqlWindowClass
    # Set only for FIXED_PAST: the latest end of the windows the SQL reads.
    window_end: Optional[datetime]
    # The class to use instead of FIXED_PAST when the result was cached before its window settled.
    fallback_class: SqlWindowClass
    clock_derived: bool = False

    @classmethod
    def of(cls, window_class: SqlWindowClass, *, clock_derived: bool = False) -> "SqlWindowClassification":
        return cls(window_class=window_class, window_end=None, fallback_class=window_class, clock_derived=clock_derived)

    def crossed_day_boundary(self, last_refresh: datetime, now: datetime, timezone: ZoneInfo) -> bool:
        # today(), yesterday() and day-relative ranges move at midnight, and the cache key does not change with them.
        # A result that reads the clock is too old once the server or project day has changed since it was cached.
        return self.clock_derived and any(
            last_refresh.astimezone(zone).date() != now.astimezone(zone).date() for zone in (_SERVER_TIMEZONE, timezone)
        )

    def class_at(self, last_refresh: datetime) -> SqlWindowClass:
        # Covers an absolute window end that had not settled yet when the result was cached: events can still
        # have landed in the window since, so the result gets the class its length gives.
        if (
            self.window_class == SqlWindowClass.FIXED_PAST
            and self.window_end is not None
            and self.window_end > last_refresh - SQL_WINDOW_SETTLE_BUFFER
        ):
            return self.fallback_class
        return self.window_class


@frozen
class _ColumnRef:
    chain: tuple[str, ...]
    unit: Optional[str]


@frozen
class _Source:
    names: frozenset[str]
    table: Optional[str]


@frozen
class _Bound:
    source: int
    column: str
    start: Optional[datetime]
    end: Optional[datetime]
    clock_derived: bool


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


def _str_constant(expr: ast.Expr) -> Optional[str]:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def _zone(name: Optional[str]) -> Optional[ZoneInfo]:
    if name is None:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
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


def _is_time_column_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in TIME_COLUMN_NAMES or lowered.endswith(TIME_COLUMN_SUFFIXES)


def _strip_instant_wrappers(expr: ast.Expr, *, allow_time_zone: bool) -> ast.Expr:
    """Unwraps calls that change how a column prints but not which instant it holds."""
    while True:
        if isinstance(expr, ast.Alias):
            expr = expr.expr
        elif isinstance(expr, ast.Call) and expr.name in ("toDateTime", "assumeNotNull") and len(expr.args) == 1:
            expr = expr.args[0]
        elif (
            allow_time_zone
            and isinstance(expr, ast.Call)
            and expr.name == "toTimeZone"
            and len(expr.args) == 2
            and _zone(_str_constant(expr.args[1])) is not None
        ):
            expr = expr.args[0]
        else:
            return expr


class _SelectCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[ast.SelectQuery] = []
        self.cte_names: set[str] = set()
        self.scalar_ctes: dict[str, ast.Expr] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        for name, cte in (node.ctes or {}).items():
            self.cte_names.add(name)
            if cte.cte_type == "column":
                # Two declarations of one name cannot be told apart, so the name stops being a column.
                self.scalar_ctes[name] = ast.Constant(value=None) if name in self.scalar_ctes else cte.expr
        super().visit_select_query(node)


class _TemporalFinder(TraversingVisitor):
    def __init__(self, aliases: dict[str, ast.Expr]) -> None:
        super().__init__()
        self.found = False
        self._aliases = aliases
        self._seen: set[str] = set()

    def visit_call(self, node: ast.Call) -> None:
        if node.name in _NOW_FUNCTIONS:
            self.found = True
        super().visit_call(node)

    def visit_constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, (datetime, date)) or (isinstance(node.value, str) and _looks_like_date(node.value)):
            self.found = True

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        self.found = True

    def visit_field(self, node: ast.Field) -> None:
        name = str(node.chain[0]) if len(node.chain) == 1 else None
        if name is not None and name in self._aliases and name not in self._seen:
            self._seen.add(name)
            self.visit(self._aliases[name])


def _looks_temporal(expr: ast.Expr, aliases: dict[str, ast.Expr]) -> bool:
    finder = _TemporalFinder(aliases)
    finder.visit(expr)
    return finder.found


class _ClockFinder(TraversingVisitor):
    """Finds what makes an expression depend on the clock: now, today, yesterday or a relative `{filters}` bound."""

    def __init__(self, filters_window: Optional[SqlTimeWindow]) -> None:
        super().__init__()
        self.found = False
        self._filters_window = filters_window

    def visit_call(self, node: ast.Call) -> None:
        if node.name in _NOW_FUNCTIONS:
            self.found = True
        super().visit_call(node)

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        window = self._filters_window
        if node.chain == ["filters", "dateRange", "from"]:
            absolute = window is not None and window.start_absolute
        elif node.chain == ["filters", "dateRange", "to"]:
            absolute = window is not None and window.end_absolute
        else:
            absolute = False
        if not absolute:
            self.found = True


class _SelectScan(TraversingVisitor):
    """What one select reads, apart from the selects nested in it. WHERE and PREWHERE are the consumed bounds."""

    def __init__(self, root: ast.SelectQuery) -> None:
        super().__init__()
        self._root = root
        self._filter_nodes = {id(node) for node in (root.where, root.prewhere) if node is not None}
        self._filter_depth = 0
        self.field_chains: list[tuple[str, ...]] = []
        self.has_filters_placeholder = False
        self.reads_clock_outside_filters = False

    def visit(self, node: Optional[ast.AST]) -> None:
        if isinstance(node, ast.SelectQuery) and node is not self._root:
            return
        in_filter = id(node) in self._filter_nodes
        self._filter_depth += in_filter
        try:
            super().visit(node)
        finally:
            self._filter_depth -= in_filter

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if not isinstance(node.table, ast.Field):
            self.visit(node.table)
        for expr in node.table_args or []:
            self.visit(expr)
        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_field(self, node: ast.Field) -> None:
        self.field_chains.append(tuple(str(part) for part in node.chain))

    def visit_call(self, node: ast.Call) -> None:
        if node.name in _NOW_FUNCTIONS and self._filter_depth == 0:
            self.reads_clock_outside_filters = True
        super().visit_call(node)

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        if _is_filters_placeholder(node):
            self.has_filters_placeholder = True
        if self._filter_depth == 0:
            self.reads_clock_outside_filters = True
        if not _is_filters_placeholder(node):
            super().visit_placeholder(node)


def _sources(select: ast.SelectQuery, cte_names: set[str]) -> list[_Source]:
    sources: list[_Source] = []
    join = select.select_from
    while join is not None:
        table = join.table
        if (
            isinstance(table, ast.Field)
            and join.table_args is None
            and not (len(table.chain) == 1 and table.chain[0] in cte_names)
        ):
            name = ".".join(str(part) for part in table.chain)
            names = {join.alias} if join.alias else {name, str(table.chain[-1])}
            sources.append(_Source(names=frozenset(names), table=name.lower()))
        else:
            chain = table.chain if isinstance(table, ast.Field) else []
            names = {join.alias} if join.alias else {str(part) for part in chain}
            sources.append(_Source(names=frozenset(names), table=None))
        join = join.next_join
    return sources


class SqlWindowClassifier:
    def __init__(
        self,
        *,
        now: datetime,
        timezone: ZoneInfo,
        filters_window: Optional[SqlTimeWindow],
        filters_read_mutable_data: bool = False,
    ) -> None:
        self._now = now.astimezone(timezone)
        self._timezone = timezone
        self._filters_window = filters_window
        self._filters_read_mutable_data = filters_read_mutable_data
        server_today = now.astimezone(_SERVER_TIMEZONE).date()
        self._server_today = datetime(server_today.year, server_today.month, server_today.day, tzinfo=timezone)

    def _constant_datetime(self, value: object, timezone: Optional[ZoneInfo] = None) -> Optional[datetime]:
        timezone = timezone or self._timezone
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=timezone)
        if isinstance(value, str) and _looks_like_date(value):
            try:
                parsed = isoparse(value)
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone)
        return None

    def _value_kind(self, expr: ast.Expr) -> Optional[str]:
        # ClickHouse adds a bare integer to a Date in days and to a DateTime in seconds.
        if isinstance(expr, ast.Alias):
            return self._value_kind(expr.expr)
        if isinstance(expr, ast.Constant):
            if isinstance(expr.value, datetime):
                return "datetime"
            return "date" if isinstance(expr.value, date) else None
        if isinstance(expr, ast.Placeholder):
            return "datetime"
        if isinstance(expr, ast.ArithmeticOperation):
            return self._value_kind(expr.left)
        if not isinstance(expr, ast.Call):
            return None
        if expr.name in _DATE_VALUED_FUNCTIONS:
            return "date"
        if expr.name in _DATETIME_VALUED_FUNCTIONS:
            return "datetime"
        if expr.name in _SHIFT_FUNCTIONS or expr.name in ("toTimeZone", "assumeNotNull"):
            return self._value_kind(expr.args[0]) if expr.args else None
        return None

    def _evaluate_delta(self, expr: ast.Expr, base: ast.Expr) -> Optional[relativedelta]:
        amount = _int_constant(expr)
        if amount is not None:
            kind = self._value_kind(base)
            if kind is None:
                return None
            return _unit_delta("day" if kind == "date" else "second", amount)
        if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
            unit = expr.name.removeprefix("toInterval").lower()
            interval_amount = _int_constant(expr.args[0])
            if unit in _UNIT_DELTAS and interval_amount is not None:
                return _unit_delta(unit, interval_amount)
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
            delta = self._evaluate_delta(args[1], args[0])
            return inner + delta * sign if inner is not None and delta is not None else None
        return None

    def _evaluate_to_datetime(self, args: list[ast.Expr], *, precision_args: int) -> Optional[datetime]:
        # toDateTime(x[, tz]) and toDateTime64(x, precision[, tz]): a time zone changes how a literal is read.
        if len(args) not in (1 + precision_args, 2 + precision_args):
            return None
        if precision_args and _int_constant(args[1]) is None:
            return None
        timezone = None
        if len(args) == 2 + precision_args:
            timezone = _zone(_str_constant(args[-1]))
            if timezone is None:
                return None
        if isinstance(args[0], ast.Constant):
            return self._constant_datetime(args[0].value, timezone)
        return self._evaluate_datetime(args[0])

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
                delta = self._evaluate_delta(expr.right, expr.left)
                return left + delta * sign if delta is not None else None
            if sign == 1:
                right = self._evaluate_datetime(expr.right)
                delta = self._evaluate_delta(expr.left, expr.right)
                return right + delta if right is not None and delta is not None else None
            return None
        if not isinstance(expr, ast.Call):
            return None
        name = expr.name
        args = expr.args
        if name in ("now", "now64", "current_timestamp"):
            return self._now
        if name in ("today", "yesterday") and not args:
            return self._server_today - timedelta(days=1 if name == "yesterday" else 0)
        if name == "toDateTime":
            return self._evaluate_to_datetime(args, precision_args=0)
        if name == "toDateTime64":
            return self._evaluate_to_datetime(args, precision_args=1)
        if name in ("parseDateTimeBestEffort", "parseDateTime64BestEffort", "assumeNotNull") and len(args) == 1:
            return self._evaluate_datetime(args[0])
        if name == "toTimeZone" and len(args) == 2 and _zone(_str_constant(args[1])) is not None:
            return self._evaluate_datetime(args[0])
        if name in _TRUNCATE_FUNCTIONS and len(args) == 1:
            inner = self._evaluate_datetime(args[0])
            return _truncate(inner, _TRUNCATE_FUNCTIONS[name], self._timezone) if inner is not None else None
        if name in _SHIFT_FUNCTIONS and len(args) == 2:
            sign, unit = _SHIFT_FUNCTIONS[name]
            inner = self._evaluate_datetime(args[0])
            amount = _int_constant(args[1])
            return inner + _unit_delta(unit, sign * amount) if inner is not None and amount is not None else None
        if name in _DATE_SHIFT_FUNCTIONS:
            return self._evaluate_date_shift(_DATE_SHIFT_FUNCTIONS[name], args)
        return None

    def _column_ref(
        self,
        expr: ast.Expr,
        aliases: dict[str, ast.Expr],
        *,
        seen: frozenset[str] = frozenset(),
        under_truncation: bool = False,
    ) -> Optional[_ColumnRef]:
        # A shift or any other function moves the bound away from the column, so only the column itself
        # and a truncation of it count. A time zone conversion inside a truncation changes its day boundary.
        expr = _strip_instant_wrappers(expr, allow_time_zone=not under_truncation)
        if isinstance(expr, ast.Field):
            chain = tuple(str(part) for part in expr.chain)
            if len(chain) == 1 and chain[0] in aliases and chain[0] not in seen:
                return self._column_ref(
                    aliases[chain[0]], aliases, seen=seen | {chain[0]}, under_truncation=under_truncation
                )
            return _ColumnRef(chain=chain, unit=None)
        if (
            isinstance(expr, ast.Call)
            and expr.name in _TRUNCATE_FUNCTIONS
            and len(expr.args) == 1
            and not under_truncation
        ):
            inner = self._column_ref(expr.args[0], aliases, seen=seen, under_truncation=True)
            if inner is not None and inner.unit is None:
                return _ColumnRef(chain=inner.chain, unit=_TRUNCATE_FUNCTIONS[expr.name])
        return None

    def _is_absolute(self, *exprs: ast.Expr) -> bool:
        finder = _ClockFinder(self._filters_window)
        for expr in exprs:
            finder.visit(expr)
        return not finder.found

    def _lower_bound(self, value: datetime, *, inclusive: bool, unit: Optional[str]) -> datetime:
        if unit is None:
            return value
        floor = _truncate(value, unit, self._timezone)
        if inclusive and floor == value:
            return value
        return floor + _UNIT_DELTAS[unit]

    def _upper_bound(self, value: datetime, *, inclusive: bool, unit: Optional[str]) -> datetime:
        if unit is None:
            return value
        floor = _truncate(value, unit, self._timezone)
        if inclusive:
            return floor + _UNIT_DELTAS[unit]
        return value if floor == value else floor + _UNIT_DELTAS[unit]

    def _attribute(self, chain: tuple[str, ...], sources: list[_Source]) -> Optional[int]:
        if len(chain) == 1:
            return 0 if len(sources) == 1 else None
        qualifier = ".".join(chain[:-1])
        for index, source in enumerate(sources):
            if qualifier in source.names:
                return index
        return None

    def _bound_from_compare(
        self,
        column_side: ast.Expr,
        op: ast.CompareOperationOp,
        value_side: ast.Expr,
        aliases: dict[str, ast.Expr],
        sources: list[_Source],
    ) -> Optional[_Bound]:
        ref = self._column_ref(column_side, aliases)
        if ref is None or not _is_time_column_name(ref.chain[-1]):
            return None
        value = self._evaluate_datetime(value_side)
        if value is None:
            return None
        source = self._attribute(ref.chain, sources)
        if source is None:
            raise _Unclassifiable()
        column = ".".join(ref.chain)
        clock_derived = not self._is_absolute(value_side)
        if op in _LOWER_BOUND_OPS:
            start = self._lower_bound(value, inclusive=op == ast.CompareOperationOp.GtEq, unit=ref.unit)
            return _Bound(source=source, column=column, start=start, end=None, clock_derived=clock_derived)
        if op in _UPPER_BOUND_OPS:
            end = self._upper_bound(value, inclusive=op == ast.CompareOperationOp.LtEq, unit=ref.unit)
            return _Bound(source=source, column=column, start=None, end=end, clock_derived=clock_derived)
        return _Bound(
            source=source,
            column=column,
            start=self._lower_bound(value, inclusive=True, unit=ref.unit),
            end=self._upper_bound(value, inclusive=True, unit=ref.unit),
            clock_derived=clock_derived,
        )

    def _bound_from_between(
        self, between: ast.BetweenExpr, aliases: dict[str, ast.Expr], sources: list[_Source]
    ) -> Optional[_Bound]:
        ref = self._column_ref(between.expr, aliases)
        if ref is None or not _is_time_column_name(ref.chain[-1]):
            return None
        low = self._evaluate_datetime(between.low)
        high = self._evaluate_datetime(between.high)
        if low is None or high is None:
            return None
        source = self._attribute(ref.chain, sources)
        if source is None:
            raise _Unclassifiable()
        return _Bound(
            source=source,
            column=".".join(ref.chain),
            start=self._lower_bound(low, inclusive=True, unit=ref.unit),
            end=self._upper_bound(high, inclusive=True, unit=ref.unit),
            clock_derived=not self._is_absolute(between.low, between.high),
        )

    def _bound_from_filters(
        self, placeholder: ast.Placeholder, aliases: dict[str, ast.Expr], sources: list[_Source]
    ) -> Optional[_Bound]:
        # A `{filters}` that cannot be pinned to one column would narrow the window in a way the classifier cannot
        # see, so it makes the query unclassifiable instead of being left out.
        window = self._filters_window
        clock_derived = window is not None and (
            (window.start is not None and not window.start_absolute)
            or (window.end is not None and not window.end_absolute)
        )
        if isinstance(placeholder.expr, ast.Field):
            if len(sources) != 1:
                raise _Unclassifiable()
            if window is None:
                return None
            return _Bound(source=0, column="{filters}", start=window.start, end=window.end, clock_derived=clock_derived)
        call = placeholder.expr
        assert isinstance(call, ast.Call)
        timestamp = next(
            (arg.expr for arg in call.args if isinstance(arg, ast.Alias) and arg.alias == _FILTERS_TIMESTAMP_KEY),
            None,
        )
        if window is None or timestamp is None or (isinstance(timestamp, ast.Constant) and timestamp.value is None):
            return None
        ref = self._column_ref(timestamp, aliases)
        source = self._attribute(ref.chain, sources) if ref is not None else None
        if ref is None or source is None:
            raise _Unclassifiable()
        return _Bound(
            source=source,
            column=".".join(ref.chain),
            start=self._lower_bound(window.start, inclusive=True, unit=ref.unit) if window.start else None,
            end=self._upper_bound(window.end, inclusive=window.end_inclusive, unit=ref.unit) if window.end else None,
            clock_derived=clock_derived,
        )

    def _bound_from_conjunct(
        self, conjunct: ast.Expr, aliases: dict[str, ast.Expr], sources: list[_Source]
    ) -> Optional[_Bound]:
        if isinstance(conjunct, ast.Placeholder) and _is_filters_placeholder(conjunct):
            return self._bound_from_filters(conjunct, aliases, sources)
        if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _FLIPPED_OPS:
            bound = self._bound_from_compare(conjunct.left, conjunct.op, conjunct.right, aliases, sources)
            if bound is None:
                bound = self._bound_from_compare(
                    conjunct.right, _FLIPPED_OPS[conjunct.op], conjunct.left, aliases, sources
                )
            if bound is not None:
                return bound
        if isinstance(conjunct, ast.BetweenExpr) and not conjunct.negated:
            bound = self._bound_from_between(conjunct, aliases, sources)
            if bound is not None:
                return bound
        if _looks_temporal(conjunct, aliases):
            raise _Unclassifiable()
        return None

    def _conjuncts(self, expr: Optional[ast.Expr]) -> list[ast.Expr]:
        if expr is None:
            return []
        if isinstance(expr, ast.And):
            return [conjunct for inner in expr.exprs for conjunct in self._conjuncts(inner)]
        return [expr]

    def _class_by_length(self, start: Optional[datetime]) -> SqlWindowClass:
        if start is None:
            return SqlWindowClass.NO_TIME_FILTER
        length = self._now - start
        if length <= LIVE_WINDOW_MAX_LENGTH:
            return SqlWindowClass.LIVE
        if length <= SHORT_WINDOW_MAX_LENGTH:
            return SqlWindowClass.UP_TO_NOW_SHORT
        return SqlWindowClass.UP_TO_NOW_LONG

    def _window_classification(
        self, start: Optional[datetime], end: Optional[datetime], *, clock_derived: bool
    ) -> SqlWindowClassification:
        by_length = self._class_by_length(start)
        if not clock_derived and end is not None and end <= self._now - SQL_WINDOW_SETTLE_BUFFER:
            return SqlWindowClassification(
                window_class=SqlWindowClass.FIXED_PAST, window_end=end, fallback_class=by_length
            )
        return SqlWindowClassification.of(by_length, clock_derived=clock_derived)

    def _merge(self, classifications: list[SqlWindowClassification]) -> SqlWindowClassification:
        # The strictest class wins. FIXED_PAST survives only when every window is past, and then it
        # settles at the latest window end and falls back to the strictest fallback.
        chosen = min(classifications, key=lambda item: _STRICTNESS_RANK[item.window_class])
        clock_derived = any(item.clock_derived for item in classifications)
        if chosen.window_class != SqlWindowClass.FIXED_PAST:
            return SqlWindowClassification.of(chosen.window_class, clock_derived=clock_derived)
        ends = [item.window_end for item in classifications if item.window_end is not None]
        return SqlWindowClassification(
            window_class=SqlWindowClass.FIXED_PAST,
            window_end=max(ends),
            fallback_class=min((item.fallback_class for item in classifications), key=_STRICTNESS_RANK.__getitem__),
            clock_derived=clock_derived,
        )

    def _reads_mutable_data(self, scan: _SelectScan, sources: list[_Source]) -> bool:
        if scan.has_filters_placeholder and self._filters_read_mutable_data:
            return True
        qualifiers = {name for source in sources for name in source.names}
        for chain in scan.field_chains:
            if len(chain) > 1 and chain[0] in qualifiers:
                chain = chain[1:]
            if chain[0] in MUTABLE_JOIN_ROOTS or chain[0].startswith(MUTABLE_JOIN_ROOT_PREFIXES):
                return True
        return False

    def _classify_select(
        self, select: ast.SelectQuery, collector: _SelectCollector
    ) -> Optional[SqlWindowClassification]:
        sources = _sources(select, collector.cte_names)
        aliases = {
            **collector.scalar_ctes,
            **{item.alias: item.expr for item in select.select if isinstance(item, ast.Alias)},
        }
        scan = _SelectScan(select)
        scan.visit(select)
        mutable = self._reads_mutable_data(scan, sources)
        starts: dict[tuple[int, str], list[datetime]] = {}
        ends: dict[tuple[int, str], list[datetime]] = {}
        clock_derived: dict[tuple[int, str], bool] = {}
        for conjunct in self._conjuncts(select.where) + self._conjuncts(select.prewhere):
            bound = self._bound_from_conjunct(conjunct, aliases, sources)
            if bound is None:
                continue
            key = (bound.source, bound.column)
            starts.setdefault(key, [])
            ends.setdefault(key, [])
            clock_derived[key] = clock_derived.get(key, scan.reads_clock_outside_filters) or bound.clock_derived
            if bound.start is not None:
                starts[key].append(bound.start)
            if bound.end is not None:
                ends[key].append(bound.end)

        classifications: list[SqlWindowClassification] = []
        for index, source in enumerate(sources):
            columns = [key for key in starts if key[0] == index]
            if mutable or (source.table is not None and (source.table not in APPEND_ONLY_TABLES or not columns)):
                classifications.append(SqlWindowClassification.of(SqlWindowClass.NO_TIME_FILTER))
                continue
            classifications.extend(
                self._window_classification(
                    start=max(starts[key]) if starts[key] else None,
                    end=min(ends[key]) if ends[key] else None,
                    clock_derived=clock_derived[key],
                )
                for key in columns
            )
        return self._merge(classifications) if classifications else None

    def classify(self, query: ast.SelectQuery | ast.SelectSetQuery) -> SqlWindowClassification:
        collector = _SelectCollector()
        collector.visit(query)
        try:
            classifications = [
                classification
                for select in collector.selects
                if (classification := self._classify_select(select, collector)) is not None
            ]
        except _Unclassifiable:
            return SqlWindowClassification.of(SqlWindowClass.UNCLASSIFIED)
        if not classifications:
            return SqlWindowClassification.of(SqlWindowClass.NO_TIME_FILTER)
        return self._merge(classifications)
