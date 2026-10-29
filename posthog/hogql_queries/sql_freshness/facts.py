import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse
from dateutil.relativedelta import relativedelta

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2
from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.functions.clickhouse.datetime import DATE_GENERATOR_FUNCTIONS
from posthog.hogql.functions.mapping import find_hogql_function
from posthog.hogql.transforms.order_by_pushdown import unwrap_alias
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.interval_specs import INTERVAL_SPECS, PERIOD_MAP

_MONDAY = 1
_JOINABLE_TABLES = (
    PersonsTable,
    PersonDistinctIdsTable,
    GroupsTable,
    SessionsTableV1,
    SessionsTableV2,
    SessionsTableV3,
)
_EXPRESSION_FIELDS = frozenset({"person_id"})
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
_TRUNCATION_SHIFTED_OPS = frozenset({ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Gt})
_FLIPPED_OPS = {
    ast.CompareOperationOp.Gt: ast.CompareOperationOp.Lt,
    ast.CompareOperationOp.GtEq: ast.CompareOperationOp.LtEq,
    ast.CompareOperationOp.Lt: ast.CompareOperationOp.Gt,
    ast.CompareOperationOp.LtEq: ast.CompareOperationOp.GtEq,
    ast.CompareOperationOp.Eq: ast.CompareOperationOp.Eq,
}


@frozen
class Window:
    start: datetime
    end: Optional[datetime]


@frozen
class _Bound:
    start: Optional[datetime]
    end: Optional[datetime]


@frozen
class QueryFacts:
    now: datetime
    start_of_today: datetime
    start_of_utc_today: datetime
    windows: tuple[Window, ...]
    relative_date_range: bool
    rolling_filters: bool
    unsupported_field: bool = False
    join: bool = False
    foreign_source: bool = False
    unbounded_select: bool = False
    unsupported_bound: bool = False
    clock_outside_bounds: bool = False
    reads_clock: bool = False
    reads_now: bool = False


@frozen
class _Value:
    at: datetime
    is_date: bool
    utc_day: bool = False


class _UnsupportedBound(Exception):
    pass


def clock_name(call: ast.Call) -> Optional[str]:
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


def _reads_supported_table(table_type: Any) -> bool:
    if isinstance(table_type, ast.VirtualTableType):
        return _reads_supported_table(table_type.table_type)
    if isinstance(table_type, ast.LazyJoinType):
        return isinstance(table_type.lazy_join.join_table, _JOINABLE_TABLES) and _reads_supported_table(
            table_type.table_type
        )
    return _events_table_type(table_type) is not None


def _is_supported_field_type(field_type: Any) -> bool:
    if isinstance(field_type, ast.FieldAliasType):
        return True
    if isinstance(field_type, ast.PropertyType):
        return _is_supported_field_type(field_type.field_type)
    if isinstance(field_type, ast.ExpressionFieldType):
        return field_type.name in _EXPRESSION_FIELDS and _reads_supported_table(field_type.table_type)
    if not isinstance(field_type, ast.FieldType):
        return False
    return _is_subquery_type(field_type.table_type) or _reads_supported_table(field_type.table_type)


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
        self.unsupported_field = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        super().visit_select_query(node)

    def visit_field(self, node: ast.Field) -> None:
        if not isinstance(node.type, ast.BaseTableType) and not _is_supported_field_type(node.type):
            self.unsupported_field = True

    def visit_call(self, node: ast.Call) -> None:
        if clock_name(node) is not None:
            self.clock_calls.add(id(node))
        super().visit_call(node)


class _Evaluator:
    def __init__(self, *, now: datetime, timezone: tzinfo, week_start_day: Optional[int]) -> None:
        self.now = now
        self.timezone = timezone
        self.week_start_day = week_start_day
        self.start_of_utc_today = _start_of_day(now, UTC)
        self.consumed_clock_calls: set[int] = set()
        self.reads_now = False

    def evaluate(self, expr: ast.Expr) -> Optional[_Value]:
        expr = unwrap_alias(expr)
        if isinstance(expr, ast.Constant):
            return self._constant(expr.value)
        if isinstance(expr, ast.Call):
            if clock_name(expr) is not None:
                return self._clock(expr)
            handler = _CALL_HANDLERS.get(expr.name)
            return handler(self, expr) if handler is not None and expr.args else None
        if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
            ast.ArithmeticOperationOp.Add,
            ast.ArithmeticOperationOp.Sub,
        ):
            base = self.evaluate(expr.left)
            delta = self._delta(expr.right, base) if base is not None else None
            if base is None or delta is None:
                return None
            moved = base.at + delta if expr.op == ast.ArithmeticOperationOp.Add else base.at - delta
            return dataclasses.replace(base, at=moved)
        return None

    def anchor(self, value: _Value) -> datetime:
        if not value.utc_day:
            return value.at
        day = value.at.astimezone(UTC).date()
        return datetime(day.year, day.month, day.day, tzinfo=self.timezone)

    def _constant(self, value: object) -> Optional[_Value]:
        if isinstance(value, datetime):
            return _Value(at=value if value.tzinfo else value.replace(tzinfo=self.timezone), is_date=False)
        if isinstance(value, date):
            return _Value(at=datetime(value.year, value.month, value.day, tzinfo=self.timezone), is_date=True)
        if isinstance(value, str) and _looks_like_date(value):
            return _parse_string(value, self.timezone)
        return None

    def _clock(self, call: ast.Call) -> Optional[_Value]:
        if call.args:
            return None
        self.consumed_clock_calls.add(id(call))
        clock = clock_name(call)
        if clock in ("now64", "now"):
            self.reads_now = True
            return _Value(at=self.now, is_date=False)
        if clock == "today":
            return _Value(at=self.start_of_utc_today, is_date=True, utc_day=True)
        if clock == "yesterday":
            return _Value(at=self.start_of_utc_today - timedelta(days=1), is_date=True, utc_day=True)
        return None

    def _delta(self, expr: ast.Expr, base: _Value) -> Optional[Union[timedelta, relativedelta]]:
        amount = _int_constant(expr)
        if amount is not None:
            return _period("day" if base.is_date else "second", amount)
        if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
            unit = expr.name.removeprefix("toInterval").lower()
            interval_amount = _int_constant(expr.args[0])
            if unit in PERIOD_MAP and interval_amount is not None:
                return _period(unit, interval_amount)
        return None

    def _wrapper(self, call: ast.Call) -> Optional[_Value]:
        timezone_arg = _string_constant(call.args[-1]) if len(call.args) > 1 else None
        literal = _string_constant(call.args[0])
        if literal is not None and _looks_like_date(literal):
            try:
                timezone = ZoneInfo(timezone_arg) if timezone_arg else self.timezone
            except (KeyError, ValueError):
                return None
            value = _parse_string(literal, timezone)
            return dataclasses.replace(value, is_date=False) if value else None
        if timezone_arg is not None:
            return None
        inner = self.evaluate(call.args[0])
        return dataclasses.replace(inner, is_date=False) if inner else None

    def _truncate(self, call: ast.Call) -> Optional[_Value]:
        inner = self.evaluate(call.args[0]) if len(call.args) == 1 else None
        if inner is None or inner.utc_day:
            return None
        week_start_day = _MONDAY if call.name == "toMonday" else self.week_start_day
        spec = INTERVAL_SPECS[_TRUNCATE_FUNCTIONS[call.name]]
        return _Value(at=spec.align(inner.at.astimezone(self.timezone), week_start_day), is_date=call.name == "toDate")

    def _shift(self, call: ast.Call) -> Optional[_Value]:
        sign, unit = _SHIFT_FUNCTIONS[call.name]
        inner = self.evaluate(call.args[0]) if len(call.args) == 2 else None
        amount = _int_constant(call.args[1]) if len(call.args) == 2 else None
        if inner is None or amount is None:
            return None
        return dataclasses.replace(inner, at=inner.at + _period(unit, sign * amount))

    def _date_shift(self, call: ast.Call) -> Optional[_Value]:
        if len(call.args) != 3:
            return None
        unit = (_string_constant(call.args[0]) or "").lower().rstrip("s")
        inner, amount = self.evaluate(call.args[2]), _int_constant(call.args[1])
        if unit not in PERIOD_MAP or inner is None or amount is None:
            return None
        return dataclasses.replace(inner, at=inner.at + _period(unit, _DATE_SHIFT_FUNCTIONS[call.name] * amount))


_CALL_HANDLERS: dict[str, Callable[[_Evaluator, ast.Call], Optional[_Value]]] = {
    **dict.fromkeys(_TIMESTAMP_WRAPPERS, _Evaluator._wrapper),
    **dict.fromkeys(_TRUNCATE_FUNCTIONS, _Evaluator._truncate),
    **dict.fromkeys(_SHIFT_FUNCTIONS, _Evaluator._shift),
    **dict.fromkeys(_DATE_SHIFT_FUNCTIONS, _Evaluator._date_shift),
}


def _column_unit(expr: ast.Expr) -> tuple[bool, Optional[str]]:
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


def _bound(
    evaluator: _Evaluator, column: ast.Expr, op: ast.CompareOperationOp, value_expr: ast.Expr
) -> Optional[_Bound]:
    is_column, unit = _column_unit(column)
    if not is_column:
        return None
    value = evaluator.evaluate(value_expr)
    if value is None:
        raise _UnsupportedBound()
    at = evaluator.anchor(value)
    step = _period(unit) if unit else timedelta()
    if op == ast.CompareOperationOp.Eq:
        return _Bound(start=at, end=at + step)
    edge = at + step if op in _TRUNCATION_SHIFTED_OPS else at
    return _Bound(start=edge, end=None) if op in _LOWER_BOUND_OPS else _Bound(start=None, end=edge)


def _bounds_from_conjunct(evaluator: _Evaluator, conjunct: ast.Expr) -> _Bound:
    if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _FLIPPED_OPS:
        bound = _bound(evaluator, conjunct.left, conjunct.op, conjunct.right)
        if bound is None:
            bound = _bound(evaluator, conjunct.right, _FLIPPED_OPS[conjunct.op], conjunct.left)
        if bound is not None:
            return bound
    if isinstance(conjunct, ast.BetweenExpr) and not conjunct.negated:
        low = _bound(evaluator, conjunct.expr, ast.CompareOperationOp.GtEq, conjunct.low)
        high = _bound(evaluator, conjunct.expr, ast.CompareOperationOp.LtEq, conjunct.high)
        if low is not None and high is not None:
            return _Bound(start=low.start, end=high.end)
    raise _UnsupportedBound()


def _select_bounds(evaluator: _Evaluator, select: ast.SelectQuery) -> list[_Bound]:
    return [
        _bounds_from_conjunct(evaluator, conjunct)
        for clause in (select.where, select.prewhere)
        if clause is not None
        for conjunct in top_level_conjuncts(clause)
        if _mentions_events_timestamp(conjunct)
    ]


def extract_facts(
    resolved_query: ast.SelectQuery | ast.SelectSetQuery,
    *,
    now: datetime,
    timezone: tzinfo,
    week_start_day: Optional[int],
    relative_date_range: bool,
    rolling_filters: bool,
) -> QueryFacts:
    now = now.astimezone(timezone)
    scan = _QueryScan()
    scan.visit(resolved_query)
    evaluator = _Evaluator(now=now, timezone=timezone, week_start_day=week_start_day)
    windows: list[Window] = []
    has_join = foreign_source = unbounded_select = unsupported_bound = False
    for select in scan.selects:
        join = select.select_from
        if join is None or _is_subquery_type(join.type):
            continue
        has_join = has_join or join.next_join is not None
        if _events_table_type(join.type) is None:
            foreign_source = True
            continue
        try:
            bounds = _select_bounds(evaluator, select)
        except _UnsupportedBound:
            unsupported_bound = True
            continue
        starts = [bound.start for bound in bounds if bound.start is not None]
        ends = [bound.end for bound in bounds if bound.end is not None]
        if not starts:
            unbounded_select = True
            continue
        windows.append(Window(start=max(starts), end=min(ends) if ends else None))
    return QueryFacts(
        now=now,
        start_of_today=_start_of_day(now, timezone),
        start_of_utc_today=evaluator.start_of_utc_today,
        windows=tuple(windows),
        relative_date_range=relative_date_range,
        rolling_filters=rolling_filters,
        unsupported_field=scan.unsupported_field,
        join=has_join,
        foreign_source=foreign_source,
        unbounded_select=unbounded_select,
        unsupported_bound=unsupported_bound,
        clock_outside_bounds=bool(scan.clock_calls - evaluator.consumed_clock_calls),
        reads_clock=bool(evaluator.consumed_clock_calls),
        reads_now=evaluator.reads_now,
    )
