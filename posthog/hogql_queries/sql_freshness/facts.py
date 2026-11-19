from datetime import UTC, datetime, tzinfo
from typing import Any, Optional
from zoneinfo import ZoneInfo

from dateutil.parser import isoparse

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.person_distinct_ids import PersonDistinctIdsTable
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2
from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3
from posthog.hogql.database.schema.util.where_clause_extractor import (
    contains_in_cohort,
    top_level_conjuncts,
    unwrap_table_alias_type,
)
from posthog.hogql.functions.clickhouse.datetime import DATE_GENERATOR_FUNCTIONS
from posthog.hogql.functions.mapping import find_hogql_function
from posthog.hogql.transforms.order_by_pushdown import unwrap_alias
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.interval_specs import INTERVAL_SPECS, PERIOD_MAP

_SUB_DAY_UNITS = frozenset({"second", "minute", "hour"})
_JOINABLE_TABLES = (
    PersonsTable,
    PersonDistinctIdsTable,
    GroupsTable,
    SessionsTableV1,
    SessionsTableV2,
    SessionsTableV3,
)
_EXPRESSION_FIELDS = frozenset({"person_id"})
_TIMESTAMP_COLUMN = "timestamp"
_LATEST_EVENT_FUNCTION_PREFIXES = ("max", "argmax", "anylast", "last_value")
_ZONE_ARGUMENT_POSITION = {"toDateTime": 1, "toDateTime64": 2, "parseDateTimeBestEffort": 1}
_NOW_FUNCTIONS = frozenset({"now", "now64"})
_EARLIEST_DATETIME = datetime(1970, 1, 1, tzinfo=UTC)
_LATEST_DATETIME = datetime(2106, 2, 7, 6, 28, 15, tzinfo=UTC)
_CLOCK_FUNCTIONS = {id(meta): meta.clickhouse_name for meta in DATE_GENERATOR_FUNCTIONS.values()} | {
    id(find_hogql_function("nowInBlock")): "nowInBlock"
}
_LOWER_BOUND_OPS = frozenset({ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq})
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
    windows: tuple[Window, ...]
    unsupported_field: bool
    join: bool
    foreign_source: bool
    unbounded_select: bool
    unsupported_bound: bool
    clock_outside_bounds: bool
    reads_now: bool
    reads_latest_event: bool


class _UnsupportedBound(Exception):
    pass


def _clock_name(call: ast.Call) -> Optional[str]:
    meta = find_hogql_function(call.name)
    return _CLOCK_FUNCTIONS.get(id(meta)) if meta is not None else None


def _is_events_table(table_type: Any) -> bool:
    table_type = unwrap_table_alias_type(table_type)
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)


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
    return _is_events_table(table_type)


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
        and _is_events_table(field_type.table_type)
    )


def _int_constant(expr: ast.Expr) -> Optional[int]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    return None


def _string_constant(expr: ast.Expr) -> Optional[str]:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def _parse_instant(value: Optional[str], timezone: tzinfo) -> Optional[datetime]:
    if value is None or not (len(value) >= 10 and value[4] == "-" and value[7] == "-" and value[:4].isdigit()):
        return None
    try:
        parsed = isoparse(value)
        if parsed.tzinfo:
            return parsed.astimezone(timezone)
        local = parsed.replace(tzinfo=timezone)
        return local if _wall_time_exists(local) else None
    except (OverflowError, ValueError):
        return None


def _wall_time_exists(at: datetime) -> bool:
    return at.astimezone(UTC).astimezone(at.tzinfo).replace(tzinfo=None) == at.replace(tzinfo=None)


def _repeats_wall_time(at: datetime, timezone: tzinfo) -> bool:
    return any(at.astimezone(zone).fold == 1 for zone in (timezone, at.tzinfo))


def _shifted(at: datetime, unit: str, amount: int) -> Optional[datetime]:
    if unit in _SUB_DAY_UNITS:
        return (at.astimezone(UTC) + PERIOD_MAP[unit] * amount).astimezone(at.tzinfo)
    moved = at + PERIOD_MAP[unit] * amount
    return moved if _wall_time_exists(moved) else None


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


def _subquery_column_types(table_type: Any, name: str) -> list[ast.Type]:
    if isinstance(table_type, ast.SelectQueryAliasType | ast.CTETableType | ast.SelectViewType):
        return _subquery_column_types(table_type.select_query_type, name)
    if isinstance(table_type, ast.SelectSetQueryType):
        return [column for query_type in table_type.types for column in _subquery_column_types(query_type, name)]
    if isinstance(table_type, ast.SelectQueryType) and name in table_type.columns:
        return [table_type.columns[name]]
    return []


class _DerivedTimestampFinder(TraversingVisitor):
    def __init__(self, alias_exprs: dict[int, ast.Expr]) -> None:
        super().__init__()
        self.alias_exprs = alias_exprs
        self.followed: set[int] = set()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = self.found or self._derives_from_events_timestamp(node.type)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def _derives_from_events_timestamp(self, field_type: Any) -> bool:
        if id(field_type) in self.followed:
            return False
        self.followed.add(id(field_type))
        if isinstance(field_type, ast.FieldAliasType):
            alias_expr = self.alias_exprs.get(id(field_type))
            if alias_expr is not None:
                self.visit(alias_expr)
                return self.found
            return self._derives_from_events_timestamp(field_type.type)
        if not isinstance(field_type, ast.FieldType):
            return False
        if field_type.name == _TIMESTAMP_COLUMN and _is_events_table(field_type.table_type):
            return True
        return any(
            self._derives_from_events_timestamp(column)
            for column in _subquery_column_types(field_type.table_type, field_type.name)
        )


class _QueryScan(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.selects: list[ast.SelectQuery] = []
        self.clock_calls: set[int] = set()
        self.unsupported_field = False
        self.alias_exprs: dict[int, ast.Expr] = {}
        self.latest_event_candidates: list[ast.Expr] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.selects.append(node)
        for order in node.order_by or []:
            position = _int_constant(order.expr)
            if order.order == "DESC" and position is not None and 0 < position <= len(node.select):
                self.latest_event_candidates.append(node.select[position - 1])
        super().visit_select_query(node)

    def visit_field(self, node: ast.Field) -> None:
        if not isinstance(node.type, ast.BaseTableType) and not _is_supported_field_type(node.type):
            self.unsupported_field = True

    def visit_call(self, node: ast.Call) -> None:
        if _clock_name(node) is not None:
            self.clock_calls.add(id(node))
        if node.name.lower().startswith(_LATEST_EVENT_FUNCTION_PREFIXES):
            self.latest_event_candidates.extend(node.args)
        super().visit_call(node)

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        if node.name.lower().startswith(_LATEST_EVENT_FUNCTION_PREFIXES):
            window_order = node.over_expr.order_by if node.over_expr is not None else None
            self.latest_event_candidates.extend(
                [*(node.exprs or []), *(node.args or []), *(order.expr for order in window_order or [])]
            )
        super().visit_window_function(node)

    def visit_order_expr(self, node: ast.OrderExpr) -> None:
        if node.order == "DESC":
            self.latest_event_candidates.append(node.expr)
        super().visit_order_expr(node)

    def visit_alias(self, node: ast.Alias) -> None:
        self.alias_exprs[id(node.type)] = node.expr
        super().visit_alias(node)

    def reads_latest_event(self) -> bool:
        finder = _DerivedTimestampFinder(self.alias_exprs)
        for candidate in self.latest_event_candidates:
            finder.visit(candidate)
        return finder.found


class _Evaluator:
    def __init__(self, *, now: datetime, timezone: tzinfo) -> None:
        self.now = now
        self.timezone = timezone
        self.consumed_clock_calls: set[int] = set()
        self.reads_now = False

    def evaluate(self, expr: ast.Expr) -> Optional[datetime]:
        at = self._value(unwrap_alias(expr))
        return at if at is not None and _EARLIEST_DATETIME <= at <= _LATEST_DATETIME else None

    def _value(self, expr: ast.Expr) -> Optional[datetime]:
        if isinstance(expr, ast.Constant):
            return _parse_instant(_string_constant(expr), self.timezone)
        if isinstance(expr, ast.Call):
            return self._call(expr)
        if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
            ast.ArithmeticOperationOp.Add,
            ast.ArithmeticOperationOp.Sub,
        ):
            if isinstance(unwrap_alias(expr.left), ast.Constant):
                return None
            base = self.evaluate(expr.left)
            step = _interval(expr.right)
            if base is None or step is None:
                return None
            unit, amount = step
            try:
                return _shifted(base, unit, -amount if expr.op == ast.ArithmeticOperationOp.Sub else amount)
            except (OverflowError, ValueError):
                return None
        return None

    def _call(self, call: ast.Call) -> Optional[datetime]:
        if _clock_name(call) in _NOW_FUNCTIONS and not call.args:
            self.consumed_clock_calls.add(id(call))
            self.reads_now = True
            return self.now
        epoch = _int_constant(call.args[0]) if len(call.args) == 1 else None
        if epoch is not None and call.name in ("toDateTime", "fromUnixTimestamp"):
            timezone = self.timezone if call.name == "toDateTime" else UTC
            try:
                return datetime.fromtimestamp(epoch, timezone)
            except (OverflowError, ValueError, OSError):
                return None
        zone_position = _ZONE_ARGUMENT_POSITION.get(call.name)
        if zone_position is None or not call.args or len(call.args) > zone_position + 1:
            return None
        if call.name == "toDateTime64" and len(call.args) > 1 and _int_constant(call.args[1]) is None:
            return None
        zone_name = _string_constant(call.args[zone_position]) if len(call.args) > zone_position else None
        if len(call.args) > zone_position and not zone_name:
            return None
        try:
            timezone = ZoneInfo(zone_name) if zone_name else self.timezone
        except (KeyError, ValueError):
            return None
        return _parse_instant(_string_constant(call.args[0]), timezone)


def _interval(expr: ast.Expr) -> Optional[tuple[str, int]]:
    if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
        unit = expr.name.removeprefix("toInterval").lower()
        amount = _int_constant(expr.args[0])
        if unit in PERIOD_MAP and amount is not None:
            return unit, amount
    return None


def _bound(
    evaluator: _Evaluator, column: ast.Expr, op: ast.CompareOperationOp, value_expr: ast.Expr
) -> Optional[_Bound]:
    if not _is_events_timestamp(column):
        return None
    at = evaluator.evaluate(value_expr)
    if at is None or _repeats_wall_time(at, evaluator.timezone):
        raise _UnsupportedBound()
    if op == ast.CompareOperationOp.Eq:
        return _Bound(start=at, end=at)
    return _Bound(start=at, end=None) if op in _LOWER_BOUND_OPS else _Bound(start=None, end=at)


def _bounds_from_conjunct(evaluator: _Evaluator, conjunct: ast.Expr) -> _Bound:
    if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _FLIPPED_OPS:
        bound = _bound(evaluator, conjunct.left, conjunct.op, conjunct.right)
        if bound is None:
            bound = _bound(evaluator, conjunct.right, _FLIPPED_OPS[conjunct.op], conjunct.left)
        if bound is not None:
            return bound
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
    resolved_query: ast.SelectQuery | ast.SelectSetQuery, *, now: datetime, timezone: tzinfo
) -> QueryFacts:
    now = now.astimezone(timezone)
    scan = _QueryScan()
    scan.visit(resolved_query)
    evaluator = _Evaluator(now=now, timezone=timezone)
    windows: list[Window] = []
    has_join = foreign_source = unbounded_select = unsupported_bound = False
    for select in scan.selects:
        join = select.select_from
        if join is None:
            continue
        has_join = has_join or join.next_join is not None
        if _is_subquery_type(join.type):
            continue
        if not _is_events_table(join.type):
            foreign_source = True
            continue
        try:
            bounds = _select_bounds(evaluator, select)
        except _UnsupportedBound:
            unsupported_bound = True
            continue
        starts = [bound.start.astimezone(UTC) for bound in bounds if bound.start is not None]
        ends = [bound.end.astimezone(UTC) for bound in bounds if bound.end is not None]
        if not starts:
            unbounded_select = True
            continue
        windows.append(Window(start=max(starts), end=min(ends) if ends else None))
    return QueryFacts(
        now=now.astimezone(UTC),
        start_of_today=INTERVAL_SPECS["day"].align(now, None),
        windows=tuple(windows),
        unsupported_field=scan.unsupported_field,
        join=has_join,
        foreign_source=foreign_source or contains_in_cohort(resolved_query),
        unbounded_select=unbounded_select or not windows,
        unsupported_bound=unsupported_bound,
        clock_outside_bounds=bool(scan.clock_calls - evaluator.consumed_clock_calls),
        reads_now=evaluator.reads_now,
        reads_latest_event=scan.reads_latest_event(),
    )
