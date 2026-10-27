"""Read flag calls from `posthog.flag_evaluations` when a query asks `events` for them.

On flag_evaluations mode 2, ingestion stops writing `$feature_flag_called` to `events`. This transform swaps a
query's `events` scan for `posthog.flag_evaluations` when `flag_evaluations` holds every row the scan selects, so
saved queries keep returning flag calls without a change.

The swap runs before type resolution, so every rule here is syntactic. A shape the rules cannot classify keeps
reading `events`.
"""

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.flag_evaluations import FlagEvaluationsTable
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.flag_called_warnings import FLAG_CALLED_EVENT
from posthog.hogql.visitor import TraversingVisitor, clone_expr

# FLAG_EVALUATIONS_TTL_DAYS - 1. That constant lives in posthog/models/flag_evaluations/sql.py, and importing it
# loads the posthog.models package, which the printer's import path avoids. The TTL can already have dropped the
# day FLAG_EVALUATIONS_TTL_DAYS back.
FLAG_EVALUATIONS_COMPLETE_DAYS = 89

_FLAG_KEY_PROPERTY = "$feature_flag"

_Predicate = Callable[[ast.Expr], bool]

# The earliest any zone's clock runs ahead of UTC.
_EARLIEST_UTC_OFFSET = timedelta(hours=14)
_DAY_IN_ANY_TIMEZONE = timedelta(days=1) + _EARLIEST_UTC_OFFSET
# A daylight-saving change moves calendar arithmetic in a timezone by up to an hour.
_DST_MARGIN = timedelta(hours=1)

_UNIT_LENGTHS: dict[str, tuple[timedelta, timedelta]] = {
    "Second": (timedelta(seconds=1), timedelta(seconds=1)),
    "Minute": (timedelta(minutes=1), timedelta(minutes=1)),
    "Hour": (timedelta(hours=1), timedelta(hours=1)),
    "Day": (timedelta(days=1), timedelta(days=1)),
    "Week": (timedelta(days=7), timedelta(days=7)),
    "Month": (timedelta(days=28), timedelta(days=31)),
    "Quarter": (timedelta(days=89), timedelta(days=92)),
    "Year": (timedelta(days=365), timedelta(days=366)),
}
_SHIFT_FUNCTIONS: dict[str, tuple[int, str]] = {
    **{f"add{unit}s": (1, unit) for unit in _UNIT_LENGTHS},
    **{f"subtract{unit}s": (-1, unit) for unit in _UNIT_LENGTHS},
}
_START_OF_UNITS = {
    "toStartOfMinute": "Minute",
    "toStartOfFiveMinutes": "Hour",
    "toStartOfTenMinutes": "Hour",
    "toStartOfFifteenMinutes": "Hour",
    "toStartOfHour": "Hour",
    "toStartOfDay": "Day",
    "toMonday": "Week",
    "toStartOfWeek": "Week",
    "toStartOfMonth": "Month",
    "toStartOfQuarter": "Quarter",
    "toStartOfYear": "Year",
}
_TIMEZONE_ARGUMENT = {"toDateTime": 1, "toDateTime64": 2, "now": 0, "now64": 1}
_COMPARISON_FUNCTIONS = {
    "equals": ast.CompareOperationOp.Eq,
    "greater": ast.CompareOperationOp.Gt,
    "greaterOrEquals": ast.CompareOperationOp.GtEq,
    "less": ast.CompareOperationOp.Lt,
    "lessOrEquals": ast.CompareOperationOp.LtEq,
}

# An alias with one of these names can shadow the column in an unqualified read.
_SCAN_COLUMNS = frozenset({"event", "timestamp", "properties"})


def can_read_flag_evaluations(node: ast.SelectQuery, now: datetime, timezone: ZoneInfo) -> bool:
    """Whether this query's `events` scan selects only rows that `flag_evaluations` holds.

    It holds when all of these hold:

    1. A top-level conjunct pins the scan's `event` to `$feature_flag_called`.
    2. A top-level conjunct bounds the scan's `timestamp` from below at or after the coverage start. A time with no
       zone reads in `timezone`, the team's zone, wherever the printer reads it that way.
    3. The scan is not sampled, because `flag_evaluations` has no sampling key. Insight runners attach `SAMPLE 1`
       to every events read, and the printer drops it, so it counts as no sampling.
    4. A top-level conjunct pins the scan's `$feature_flag` property to non-empty strings that no other JSON value
       prints as. Ingestion writes a call to `flag_evaluations` only when its `$feature_flag` is a non-empty JSON
       string, and leaves every other call in `events` on every flag_evaluations mode. A literal such as `'100'`
       also matches the number 100, which stays in `events`.
    5. The select list has no `*` or `COLUMNS(...)`, and the scan has no column aliases. `flag_evaluations` has
       other columns, so either one would change what the query reads.

    The caller checks the rest with `swap_keeps_bindings`: every name in the swapped query binds as it did before.
    """
    scan = _EventsScan.of(node)
    if scan is None or (scan.join.sample is not None and not scan.join.sample.samples_all_rows()):
        return False
    if scan.expands_columns(node.select):
        return False
    conjuncts = _conjuncts(node.where) + _conjuncts(node.prewhere)
    return scan.pins_flag_calls(conjuncts, needs_flag_key=True) and scan.bounds_timestamp(conjuncts, now, timezone)


def rewrite_flag_calls_to_flag_evaluations(node: _T_AST, context: HogQLContext) -> _T_AST | None:
    """A clone of `node` whose qualifying `events` scans read `posthog.flag_evaluations`, or None when none qualifies."""
    if context.database is None or not context.database.read_flag_calls_from_flag_evaluations:
        return None
    finder = _FlagCalledConstantFinder()
    finder.visit(node)
    if not finder.found:
        return None
    cloned = clone_expr(node)
    swapper = _EventsScanSwapper(now=datetime.now(UTC), timezone=ZoneInfo(context.database.get_timezone()))
    swapper.visit(cloned)
    return cloned if swapper.swapped else None


class _EventsScan:
    def __init__(self, join: ast.JoinExpr, alias: str, has_other_sources: bool):
        self.join = join
        self.alias = alias
        self.has_other_sources = has_other_sources
        self.shadowed: frozenset[str] = frozenset()

    @classmethod
    def of(cls, node: ast.SelectQuery) -> "_EventsScan | None":
        join = node.select_from
        if (
            join is None
            or not isinstance(join.table, ast.Field)
            or join.table.chain != ["events"]
            or join.table_args is not None
            or join.table_final
            or join.column_aliases
        ):
            return None
        scan = cls(
            join=join,
            alias=join.alias or "events",
            # A field without a table prefix can bind to a joined table or an ARRAY JOIN alias instead.
            has_other_sources=join.next_join is not None or bool(node.array_join_list),
        )
        collector = _AliasCollector(node)
        collector.visit(node)
        # An alias such as `e.timestamp AS timestamp` reads the column it names, so it changes no read.
        scan.shadowed = frozenset(
            name for name, expr in collector.aliases if name in _SCAN_COLUMNS and scan.column(expr) != [name]
        )
        return scan

    def column(self, expr: ast.Expr) -> list[str | int] | None:
        """The chain below the scan when `expr` reads it, such as `["event"]` or `["properties", "$feature_flag"]`."""
        if not isinstance(expr, ast.Field) or not expr.chain:
            return None
        if expr.chain[0] == self.alias and len(expr.chain) > 1:
            return expr.chain[1:]
        if self.has_other_sources or expr.chain[0] in self.shadowed:
            return None
        return expr.chain

    def expands_columns(self, select: list[ast.Expr]) -> bool:
        for item in select:
            while isinstance(item, ast.Alias):
                item = item.expr
            if isinstance(item, ast.ColumnsExpr) or (isinstance(item, ast.Field) and item.chain[-1:] == ["*"]):
                return True
        return False

    def pins_flag_calls(self, conjuncts: list[ast.Expr], needs_flag_key: bool) -> bool:
        needs_flag_key = needs_flag_key and not any(self._pins_flag_key(conjunct) for conjunct in conjuncts)
        return any(self._pins_flag_calls_in(conjunct, needs_flag_key) for conjunct in conjuncts)

    def _pins_flag_calls_in(self, expr: ast.Expr, needs_flag_key: bool) -> bool:
        if _pins(expr, self._reads_event, _is_flag_called):
            return not needs_flag_key
        if isinstance(expr, ast.Or):
            return bool(expr.exprs) and all(
                self.pins_flag_calls(_conjuncts(branch), needs_flag_key) for branch in expr.exprs
            )
        return False

    def _pins_flag_key(self, expr: ast.Expr) -> bool:
        if _pins(expr, self._reads_flag_key, _is_flag_key):
            return True
        if isinstance(expr, ast.Or):
            return bool(expr.exprs) and all(self._pins_flag_key(branch) for branch in expr.exprs)
        return False

    def flag_keys(self, conjuncts: list[ast.Expr]) -> list[str]:
        """The keys a top-level conjunct pins `$feature_flag` to, or an empty list when no top-level conjunct does."""
        for conjunct in conjuncts:
            if self._pins_flag_key(conjunct):
                return _pinned_values(conjunct)
        return []

    def _reads_event(self, expr: ast.Expr) -> bool:
        return self.column(expr) == ["event"]

    def _reads_flag_key(self, expr: ast.Expr) -> bool:
        if isinstance(expr, ast.ArrayAccess):
            return self.column(expr.array) == ["properties"] and _is_constant(expr.property, _FLAG_KEY_PROPERTY)
        if isinstance(expr, ast.Call) and expr.name == "JSONExtractString" and len(expr.args) == 2:
            return self.column(expr.args[0]) == ["properties"] and _is_constant(expr.args[1], _FLAG_KEY_PROPERTY)
        return self.column(expr) == ["properties", _FLAG_KEY_PROPERTY]

    def bounds_timestamp(self, conjuncts: list[ast.Expr], now: datetime, timezone: ZoneInfo) -> bool:
        coverage_start = _utc_midnight(now) - timedelta(days=FLAG_EVALUATIONS_COMPLETE_DAYS)
        for conjunct in conjuncts:
            bound = self._lower_bound(conjunct)
            if bound is None:
                continue
            try:
                value = _earliest_instant(bound, now, timezone)
            except OverflowError:
                # A date near year 1 or 9999, or a huge interval, leaves datetime's range.
                continue
            if value is not None and value >= coverage_start:
                return True
        return False

    def _lower_bound(self, expr: ast.Expr) -> ast.Expr | None:
        if isinstance(expr, ast.BetweenExpr):
            return expr.low if not expr.negated and self._reads_timestamp(expr.expr) else None
        comparison = _comparison(expr)
        if comparison is None:
            return None
        op, left, right = comparison
        if op in (ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Gt) and self._reads_timestamp(left):
            return right
        if op in (ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Lt) and self._reads_timestamp(right):
            return left
        return None

    def _reads_timestamp(self, expr: ast.Expr) -> bool:
        return self.column(expr) == ["timestamp"]


def _comparison(expr: ast.Expr) -> tuple[ast.CompareOperationOp, ast.Expr, ast.Expr] | None:
    """`expr` as an operator and its operands, whether it is written `a >= b` or `greaterOrEquals(a, b)`."""
    if isinstance(expr, ast.CompareOperation):
        return expr.op, expr.left, expr.right
    if isinstance(expr, ast.Call) and expr.name in _COMPARISON_FUNCTIONS and len(expr.args) == 2:
        return _COMPARISON_FUNCTIONS[expr.name], expr.args[0], expr.args[1]
    return None


def _pins(expr: ast.Expr, reads: _Predicate, accepts: _Predicate) -> bool:
    """Whether `expr` limits what `reads` matches to values that `accepts` matches."""
    comparison = _comparison(expr)
    if comparison is None:
        return False
    op, left, right = comparison
    if op == ast.CompareOperationOp.Eq:
        return (reads(left) and accepts(right)) or (reads(right) and accepts(left))
    if op in (ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn):
        values = right.exprs if isinstance(right, (ast.Tuple, ast.Array)) else [right]
        return reads(left) and bool(values) and all(accepts(value) for value in values)
    return False


def _is_constant(expr: ast.Expr, value: str) -> bool:
    return isinstance(expr, ast.Constant) and expr.value == value


def _is_flag_called(expr: ast.Expr) -> bool:
    return _is_constant(expr, FLAG_CALLED_EVENT)


def _is_flag_key(expr: ast.Expr) -> bool:
    if not isinstance(expr, ast.Constant) or not isinstance(expr.value, str) or expr.value == "":
        return False
    # A property read compares the value's JSON text, so a literal that parses as JSON can match a non-string value.
    try:
        json.loads(expr.value)
    except ValueError:
        return True
    return False


def _pinned_values(expr: ast.Expr) -> list[str]:
    if isinstance(expr, ast.Or):
        return [value for branch in expr.exprs for value in _pinned_values(branch)]
    comparison = _comparison(expr)
    if comparison is None:
        return []
    _, left, right = comparison
    values = right.exprs if isinstance(right, (ast.Tuple, ast.Array)) else [left, right]
    return [value.value for value in values if isinstance(value, ast.Constant) and isinstance(value.value, str)]


def _conjuncts(expr: ast.Expr | None) -> list[ast.Expr]:
    return top_level_conjuncts(expr) if expr is not None else []


def _utc_midnight(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)


def _earliest_instant(expr: ast.Expr, now: datetime, timezone: ZoneInfo) -> datetime | None:
    """An instant no later than the value of `expr`, or None when `expr` has a shape this cannot evaluate."""
    if isinstance(expr, ast.Constant):
        # The printer prints a naive datetime in the server's zone, which is UTC. A bare string compares in UTC or
        # in the team's zone.
        return _constant_instant(expr.value, (timezone, UTC))
    shift = _shift(expr)
    if shift is not None:
        base, interval, sign = shift
        return _shifted(_earliest_instant(base, now, timezone), interval, sign)
    if not isinstance(expr, ast.Call):
        return None
    name, args = expr.name, expr.args
    if name in ("now", "now64"):
        return now
    if name == "today" and not args:
        return _utc_midnight(now) - _DAY_IN_ANY_TIMEZONE
    if name == "assumeNotNull" and len(args) == 1:
        return _earliest_instant(args[0], now, timezone)
    if name in ("toDateTime", "toDateTime64") and args:
        zones = _zones_of(expr, timezone)
        if isinstance(args[0], ast.Constant):
            return _constant_instant(args[0].value, zones) if zones else None
        return _earliest_instant(args[0], now, timezone)
    if name == "toDate" and args:
        instant = _earliest_instant(args[0], now, timezone)
        # toDate truncates to a day, and the comparison can read that day in a zone the caller does not name.
        return instant - _DAY_IN_ANY_TIMEZONE if instant is not None else None
    day_start = _start_of_day(expr, now, timezone)
    if day_start is not None:
        return day_start
    if name in _START_OF_UNITS and args:
        return _shifted(_earliest_instant(args[0], now, timezone), (1, _START_OF_UNITS[name]), -1)
    if name == "toStartOfInterval" and len(args) >= 2:
        return _shifted(_earliest_instant(args[0], now, timezone), _interval(args[1]), -1)
    return None


def _start_of_day(expr: ast.Call, now: datetime, timezone: ZoneInfo) -> datetime | None:
    """The exact start of the day `toStartOfDay(x)` or `toStartOfInterval(x, toIntervalDay(1))` rounds to, or None
    for any other call or when the zone it rounds in is unknown."""
    if expr.name == "toStartOfDay" and expr.args:
        zone_index = 1
    elif expr.name == "toStartOfInterval" and len(expr.args) >= 2 and _interval(expr.args[1]) == (1, "Day"):
        zone_index = 2
    else:
        return None
    value = expr.args[0]
    instant = _earliest_instant(value, now, timezone)
    # ClickHouse rounds in the zone argument, or else in the zone of the value.
    zones = _zone(expr.args[zone_index]) if len(expr.args) > zone_index else _zones_of(value, timezone)
    if instant is None or not zones:
        return None
    return min(datetime.combine(instant.astimezone(zone).date(), time.min, tzinfo=zone) for zone in zones)


def _zones_of(expr: ast.Expr, timezone: ZoneInfo) -> tuple[tzinfo, ...]:
    """The zones a time value can carry. Empty when it names a zone that does not parse."""
    while True:
        shift = _shift(expr)
        if shift is not None:
            expr = shift[0]
        elif isinstance(expr, ast.Call) and expr.name == "assumeNotNull" and len(expr.args) == 1:
            expr = expr.args[0]
        else:
            break
    if isinstance(expr, ast.Call) and expr.name in _TIMEZONE_ARGUMENT:
        zone_index = _TIMEZONE_ARGUMENT[expr.name]
        # The printer adds the team's zone to each of these calls that names none.
        return _zone(expr.args[zone_index]) if len(expr.args) > zone_index else (timezone,)
    return (timezone, UTC)


def _zone(expr: ast.Expr) -> tuple[tzinfo, ...]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        try:
            return (ZoneInfo(expr.value),)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ()


def _shift(expr: ast.Expr) -> tuple[ast.Expr, tuple[int, str] | None, int] | None:
    """`expr` as a base, an interval and a sign when it adds an interval to a time or subtracts one."""
    if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
        ast.ArithmeticOperationOp.Add,
        ast.ArithmeticOperationOp.Sub,
    ):
        return expr.left, _interval(expr.right), 1 if expr.op == ast.ArithmeticOperationOp.Add else -1
    if not isinstance(expr, ast.Call) or len(expr.args) != 2:
        return None
    if expr.name in ("plus", "minus"):
        return expr.args[0], _interval(expr.args[1]), 1 if expr.name == "plus" else -1
    if expr.name in _SHIFT_FUNCTIONS and (count := _integer(expr.args[1])) is not None:
        sign, unit = _SHIFT_FUNCTIONS[expr.name]
        return expr.args[0], (count, unit), sign
    return None


def _interval(expr: ast.Expr) -> tuple[int, str] | None:
    if isinstance(expr, ast.Call) and expr.name.startswith("toInterval") and len(expr.args) == 1:
        unit = expr.name.removeprefix("toInterval")
        count = _integer(expr.args[0])
        if unit in _UNIT_LENGTHS and count is not None:
            return count, unit
    return None


def _shifted(instant: datetime | None, interval: tuple[int, str] | None, sign: int) -> datetime | None:
    """The earliest instant `instant` plus `sign` times `interval` can be."""
    if instant is None or interval is None:
        return None
    count, unit = interval
    shortest, longest = _UNIT_LENGTHS[unit]
    total = sign * count
    return instant + total * (shortest if total >= 0 else longest) - _DST_MARGIN


def _integer(expr: ast.Expr) -> int | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    return None


def _constant_instant(value: object, zones: tuple[tzinfo, ...]) -> datetime | None:
    """`value` as an instant, reading a naive value in whichever of `zones` gives the earliest one."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value
    return min(value.replace(tzinfo=zone) for zone in zones)


class _SyntaxVisitor(TraversingVisitor):
    def visit_field(self, node: ast.Field) -> None:
        # The inherited visit follows the field's type into shared CTE types, which takes exponential time. An
        # earlier step can resolve parts of the tree in place.
        pass


class _AliasCollector(_SyntaxVisitor):
    def __init__(self, root: ast.SelectQuery) -> None:
        super().__init__()
        self.root = root
        self.aliases: list[tuple[str, ast.Expr]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A subquery's aliases do not reach the outer scope.
        if node is self.root:
            super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_alias(self, node: ast.Alias) -> None:
        self.aliases.append((node.alias, node.expr))
        super().visit_alias(node)


class _FlagCalledConstantFinder(_SyntaxVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_constant(self, node: ast.Constant) -> None:
        if node.value == FLAG_CALLED_EVENT:
            self.found = True


class _EventsScanSwapper(_SyntaxVisitor):
    def __init__(self, now: datetime, timezone: ZoneInfo) -> None:
        super().__init__()
        self.now = now
        self.timezone = timezone
        self.swapped = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        scan = _EventsScan.of(node)
        if scan is not None and can_read_flag_evaluations(node, self.now, self.timezone):
            self._swap(node, scan)
        super().visit_select_query(node)

    def _swap(self, node: ast.SelectQuery, scan: _EventsScan) -> None:
        keys = scan.flag_keys(_conjuncts(node.where) + _conjuncts(node.prewhere))
        # The old alias keeps qualified reads such as `events.timestamp` resolving.
        scan.join.alias = scan.alias
        scan.join.table = ast.Field(chain=["posthog", "flag_evaluations"])
        # A swapped PREWHERE can read person columns through a join that the printer adds later. ClickHouse
        # rejects a PREWHERE that reads a joined column, and WHERE selects the same rows.
        conditions = [condition for condition in (node.prewhere, node.where) if condition is not None]
        # flag_key sorts the table, so this predicate lets ClickHouse skip other flags. The pin implies it when no
        # key holds a backslash, because the stored text of such a key has no JSON escapes.
        if keys and not any("\\" in key for key in keys):
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=[scan.alias, "flag_key"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=key) for key in keys]),
                )
            )
        node.prewhere = None
        node.where = conditions[0] if len(conditions) == 1 else ast.And(exprs=conditions)
        self.swapped = True


def swap_keeps_bindings(original: ast.AST, swapped: ast.AST) -> bool:
    """Whether every field and table in the resolved swapped query binds as it does in the resolved original.

    The swap may change only the table each swapped scan reads. A name that binds elsewhere changes the result
    with no resolution error: a `WITH` name that a `flag_evaluations` column now shadows, a `COLUMNS(...)` that
    expands to other columns, or a `FROM events` that read a CTE named `events`. The comparison ignores order,
    because the swap moves `PREWHERE` into `WHERE`.
    """
    swapped_bindings = Counter(binding for binding in _bindings(swapped) if binding != _ADDED_FLAG_KEY_READ)
    return Counter(_bindings(original)) == swapped_bindings


# A field records the last part of its chain, so `e.person_id` and `person_id` match.
_Binding = tuple[str, str | int, tuple[str, ...]]

# events has no flag_key column. In a query that resolves on events, only the predicate the swap adds reads one.
_ADDED_FLAG_KEY_READ: _Binding = ("field", "flag_key", ("scan",))


def _bindings(node: ast.AST) -> list[_Binding]:
    collector = _BindingCollector()
    collector.visit(node)
    return collector.bindings


class _BindingCollector(_SyntaxVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.bindings: list[_Binding] = []

    def visit_field(self, node: ast.Field) -> None:
        self.bindings.append(("field", node.chain[-1] if node.chain else "", _target(node.type)))

    def visit_alias(self, node: ast.Alias) -> None:
        if not node.hidden:
            super().visit_alias(node)
            return
        # The resolver replaces an expression field, such as flag_evaluations.person_id, with a hidden alias named
        # after the field. The same field can be a plain column on events, so only the alias name and what the
        # expansion reads count.
        expansion = _bindings(node.expr)
        reads_scan = bool(expansion) and all(target == ("scan",) for _, _, target in expansion)
        self.bindings.append(("field", node.alias, ("scan",) if reads_scan else ("expression",)))

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        self.bindings.append(("table", "", _target(node.type)))
        if not isinstance(node.table, ast.Field):
            self.visit(node.table)
        for arg in node.table_args or []:
            self.visit(arg)
        self.visit(node.constraint)
        self.visit(node.next_join)


def _target(current: ast.Type | None) -> tuple[str, ...]:
    """What a resolved field or table reads from: `("scan",)` for an events or flag_evaluations scan."""
    while True:
        if isinstance(current, ast.FieldAliasType):
            current = current.type
        elif isinstance(current, ast.PropertyType):
            current = current.field_type
        elif isinstance(
            current,
            (
                ast.FieldType,
                ast.ExpressionFieldType,
                ast.FieldTraverserType,
                ast.TableAliasType,
                ast.LazyJoinType,
                ast.VirtualTableType,
            ),
        ):
            current = current.table_type
        elif isinstance(current, ast.TableType):
            return (
                ("scan",)
                if isinstance(current.table, (EventsTable, FlagEvaluationsTable))
                else ("table", current.table.__class__.__name__)
            )
        elif isinstance(current, ast.CTETableType):
            return ("cte", current.name)
        elif isinstance(current, ast.CTETableAliasType):
            return ("cte", current.alias)
        elif isinstance(current, ast.SelectQueryAliasType):
            return ("subquery", current.alias)
        elif isinstance(current, ast.SelectViewType):
            return ("view", current.view_name)
        else:
            return (current.__class__.__name__,)
