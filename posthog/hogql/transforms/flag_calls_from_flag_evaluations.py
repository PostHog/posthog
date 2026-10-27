"""Read flag calls from `posthog.flag_evaluations` when a query asks `events` for them.

On flag_evaluations mode 2, ingestion stops writing `$feature_flag_called` to `events`. This transform swaps a
query's `events` scan for `posthog.flag_evaluations` when `flag_evaluations` holds every row the scan selects, so
saved queries keep returning flag calls without a change.

The swap runs before type resolution, so every rule here is syntactic. A shape the rules cannot classify keeps
reading `events`.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.flag_called_warnings import FLAG_CALLED_EVENT
from posthog.hogql.visitor import TraversingVisitor, clone_expr

# FLAG_EVALUATIONS_TTL_DAYS - 1. That constant lives in posthog/models/flag_evaluations/sql.py, and importing it
# loads the posthog.models package, which the printer's import path avoids. The TTL can already have dropped the
# day FLAG_EVALUATIONS_TTL_DAYS back.
FLAG_EVALUATIONS_COMPLETE_DAYS = 89

_FLAG_KEY_PROPERTY = "$feature_flag"

_Predicate = Callable[[ast.Expr], bool]

# A naive time can belong to any team timezone. Read in UTC+14, it gives the earliest instant it can mean.
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
_TIMEZONE_ARGUMENT = {"toDateTime": 1, "toDateTime64": 2, "toDate": 1}
_COMPARISON_FUNCTIONS = {
    "equals": ast.CompareOperationOp.Eq,
    "greater": ast.CompareOperationOp.Gt,
    "greaterOrEquals": ast.CompareOperationOp.GtEq,
    "less": ast.CompareOperationOp.Lt,
    "lessOrEquals": ast.CompareOperationOp.LtEq,
}

# An alias with one of these names can shadow the column in an unqualified read.
_SCAN_COLUMNS = frozenset({"event", "timestamp", "properties"})


def can_read_flag_evaluations(node: ast.SelectQuery, now: datetime) -> bool:
    """Whether this query's `events` scan selects only rows that `flag_evaluations` holds.

    It holds when all of these hold:

    1. A top-level conjunct pins the scan's `event` to `$feature_flag_called`.
    2. A top-level conjunct bounds the scan's `timestamp` from below at or after the coverage start.
    3. The scan is not sampled, because `flag_evaluations` has no sampling key. Insight runners attach `SAMPLE 1`
       to every events read, and the printer drops it, so it counts as no sampling.
    4. A top-level conjunct pins the scan's `$feature_flag` property to non-empty strings. Ingestion writes a call
       to `flag_evaluations` only when its `$feature_flag` is a non-empty string, and leaves every other call in
       `events` on every flag_evaluations mode.
    5. The select list does not expand the scan's columns with `*` or `COLUMNS(...)`. `flag_evaluations` has
       other columns, so the result would change shape.

    The caller checks the last condition, that every field the query reads exists on `flag_evaluations`, by
    resolving the swapped query.
    """
    scan = _EventsScan.of(node)
    if scan is None or (scan.join.sample is not None and not scan.join.sample.samples_all_rows()):
        return False
    if scan.expands_columns(node.select):
        return False
    conjuncts = _conjuncts(node.where) + _conjuncts(node.prewhere)
    return scan.pins_flag_calls(conjuncts, needs_flag_key=True) and scan.bounds_timestamp(conjuncts, now)


def rewrite_flag_calls_to_flag_evaluations(node: _T_AST, context: HogQLContext) -> _T_AST | None:
    """A clone of `node` whose qualifying `events` scans read `posthog.flag_evaluations`, or None when none qualifies."""
    if context.database is None or not context.database.read_flag_calls_from_flag_evaluations:
        return None
    finder = _FlagCalledConstantFinder()
    finder.visit(node)
    if not finder.found:
        return None
    cloned = clone_expr(node)
    swapper = _EventsScanSwapper(now=datetime.now(UTC))
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
            if isinstance(item, ast.ColumnsExpr) or self.column(item) == ["*"]:
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

    def _reads_event(self, expr: ast.Expr) -> bool:
        return self.column(expr) == ["event"]

    def _reads_flag_key(self, expr: ast.Expr) -> bool:
        if isinstance(expr, ast.ArrayAccess):
            return self.column(expr.array) == ["properties"] and _is_constant(expr.property, _FLAG_KEY_PROPERTY)
        if isinstance(expr, ast.Call) and expr.name == "JSONExtractString" and len(expr.args) == 2:
            return self.column(expr.args[0]) == ["properties"] and _is_constant(expr.args[1], _FLAG_KEY_PROPERTY)
        return self.column(expr) == ["properties", _FLAG_KEY_PROPERTY]

    def bounds_timestamp(self, conjuncts: list[ast.Expr], now: datetime) -> bool:
        coverage_start = _utc_midnight(now) - timedelta(days=FLAG_EVALUATIONS_COMPLETE_DAYS)
        for conjunct in conjuncts:
            bound = self._lower_bound(conjunct)
            if bound is None:
                continue
            try:
                value = _earliest_instant(bound, now)
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
    return isinstance(expr, ast.Constant) and isinstance(expr.value, str) and expr.value != ""


def _conjuncts(expr: ast.Expr | None) -> list[ast.Expr]:
    return top_level_conjuncts(expr) if expr is not None else []


def _utc_midnight(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)


def _earliest_instant(expr: ast.Expr, now: datetime) -> datetime | None:
    """An instant no later than the value of `expr`, or None when `expr` has a shape this cannot evaluate."""
    if isinstance(expr, ast.Constant):
        return _constant_instant(expr.value, timezone=None)
    shift = _shift(expr)
    if shift is not None:
        base, interval, sign = shift
        return _shifted(_earliest_instant(base, now), interval, sign)
    if not isinstance(expr, ast.Call):
        return None
    name, args = expr.name, expr.args
    if name in ("now", "now64"):
        return now
    if name == "today" and not args:
        return _utc_midnight(now) - _DAY_IN_ANY_TIMEZONE
    if name == "assumeNotNull" and len(args) == 1:
        return _earliest_instant(args[0], now)
    if name in _TIMEZONE_ARGUMENT and args:
        timezone_index = _TIMEZONE_ARGUMENT[name]
        timezone = args[timezone_index] if len(args) > timezone_index else None
        if isinstance(args[0], ast.Constant):
            timezone_name = (
                timezone.value if isinstance(timezone, ast.Constant) and isinstance(timezone.value, str) else None
            )
            instant = _constant_instant(args[0].value, timezone_name)
        else:
            instant = _earliest_instant(args[0], now)
        if name == "toDate" and instant is not None:
            return instant - _DAY_IN_ANY_TIMEZONE
        return instant
    if name in _START_OF_UNITS and args:
        return _shifted(_earliest_instant(args[0], now), (1, _START_OF_UNITS[name]), -1)
    if name == "toStartOfInterval" and len(args) >= 2:
        return _shifted(_earliest_instant(args[0], now), _interval(args[1]), -1)
    return None


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


def _constant_instant(value: object, timezone: str | None) -> datetime | None:
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
    if timezone is not None:
        try:
            return value.replace(tzinfo=ZoneInfo(timezone))
        except (ZoneInfoNotFoundError, ValueError):
            return None
    return value.replace(tzinfo=UTC) - _EARLIEST_UTC_OFFSET


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
    def __init__(self, now: datetime) -> None:
        super().__init__()
        self.now = now
        self.swapped = False
        # One entry per enclosing select: whether it defines a CTE named `events`, which takes the table's place.
        self._events_cte_scopes: list[bool] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self._events_cte_scopes.append("events" in (node.ctes or {}))
        try:
            join = node.select_from
            if join is not None and not any(self._events_cte_scopes) and can_read_flag_evaluations(node, self.now):
                # The old alias keeps qualified reads such as `events.timestamp` resolving.
                join.alias = join.alias or "events"
                join.table = ast.Field(chain=["posthog", "flag_evaluations"])
                self.swapped = True
            super().visit_select_query(node)
        finally:
            self._events_cte_scopes.pop()
