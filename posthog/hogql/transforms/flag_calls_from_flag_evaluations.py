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
from functools import cache, partial
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.flag_evaluations import ELEMENT_STAND_INS, FlagEvaluationsTable
from posthog.hogql.database.schema.util.where_clause_extractor import top_level_conjuncts
from posthog.hogql.errors import BaseHogQLError, QueryError
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING, find_hogql_function
from posthog.hogql.property_metadata import load_property_metadata
from posthog.hogql.utils import is_json_verbatim
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.date_util import start_of_day

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

logger = structlog.get_logger(__name__)

# At most FLAG_EVALUATIONS_TTL_DAYS - 1, because the TTL can already have dropped the day FLAG_EVALUATIONS_TTL_DAYS
# back. It stays lower while the table still lacks the oldest days that a shorter TTL dropped. The TTL constant
# lives in posthog/models/flag_evaluations/sql.py, and importing it loads the posthog.models package, which the
# printer's import path avoids.
FLAG_EVALUATIONS_COMPLETE_DAYS = 89

_FLAG_KEY_PROPERTY = "$feature_flag"

_Predicate = Callable[[ast.Expr], bool]

_MAX_UTC_OFFSET = timedelta(hours=14)
# How far before UTC midnight a date can start in some zone. A zone behind UTC can still be on the previous date, and
# a zone 14 hours ahead of UTC starts that date 14 hours before UTC does.
_DAY_IN_ANY_TIMEZONE = timedelta(days=1) + _MAX_UTC_OFFSET
# A daylight-saving change moves calendar arithmetic in a timezone by up to two hours. Antarctica/Troll changes by
# two hours.
_DST_MARGIN = timedelta(hours=2)

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
# Rounding to a week or longer returns a Date. A comparison with a DateTime reads a Date at midnight UTC. In a zone
# behind UTC, that midnight comes before the local midnight that the rounding chose.
_DATE_UNITS = frozenset({"Week", "Month", "Quarter", "Year"})

# An alias with one of these names can shadow the column in an unqualified read.
_SCAN_COLUMNS = frozenset({"event", "timestamp", "properties"})


def can_read_flag_evaluations(
    node: ast.SelectQuery,
    now: datetime,
    timezone: ZoneInfo,
    *,
    only_in_flag_evaluations: bool = False,
    flag_key_compares_as_string: bool = True,
) -> bool:
    """Whether this query's `events` scan selects only rows that `flag_evaluations` holds.

    It holds when all of these hold:

    1. A top-level conjunct pins the scan's `event` to `$feature_flag_called`.
    2. A top-level conjunct bounds the scan's `timestamp` from below at or after the coverage start. A time with no
       zone reads in `timezone`, the team's zone, wherever the printer reads it that way.
    3. The scan is not sampled, because `flag_evaluations` has no sampling key. Insight runners attach `SAMPLE 1`
       to every events read, and the printer drops it, so it counts as no sampling.
    4. The scan's `$feature_flag` property is pinned to non-empty strings that no other JSON value prints as. A
       top-level conjunct can pin it for the whole scan. Otherwise, each `OR` branch that pins `event` must pin it
       too, as an action with several steps does. Ingestion writes a call to `flag_evaluations` only when its
       `$feature_flag` is a non-empty JSON string, and leaves every other call in `events` on every
       flag_evaluations mode. A literal such as `'100'` also matches the number 100, which stays in `events`.
       Without `flag_key_compares_as_string`, nothing pins `$feature_flag`: the team's property definition gives it
       a type, and a comparison converts the value first. Under a Boolean type, `'TRUE'` matches the key "true" and
       the JSON value true.
    5. The select list has no `*` or `COLUMNS(...)`, and the scan has no column aliases. `flag_evaluations` has
       other columns, so either one would change what the query reads.
    6. The scan has no `FINAL` and no table arguments.

    With `only_in_flag_evaluations`, conditions 2 and 4 do not apply. Ingestion writes no new flag calls to events
    then, so the scan reads `flag_evaluations` even when that leaves out calls older than its coverage or calls
    without a flag key.

    `resolve_flag_calls_from_flag_evaluations` checks the rest after resolution: every name in the swapped query
    binds as it did before.
    """
    scan = EventsScan.of(node, lambda: flag_key_compares_as_string)
    return scan is not None and _qualifies(
        scan, node, filter_conjuncts(node), now, timezone, only_in_flag_evaluations=only_in_flag_evaluations
    )


def resolve_flag_calls_from_flag_evaluations(
    node: _T_AST, context: HogQLContext, resolve: Callable[[_T_AST], _T_AST]
) -> _T_AST:
    """`node` resolved with `resolve`, with each `events` scan that `can_read_flag_evaluations` accepts reading
    `posthog.flag_evaluations` instead.

    This returns the swapped query only when it resolves and every name in it binds as it does in the original.
    Otherwise it returns the resolved original. For an organization whose flag calls are only in
    `flag_evaluations`, it raises a QueryError instead of returning the original. It also raises before it
    resolves anything when such an organization's query has a scan of only flag calls with a shape that
    `flag_evaluations` cannot stand in for.

    While `events` still gets flag calls, the original query is the answer whenever the two tables can read a row
    differently:

    - A project that reads the native-JSON events table keeps reading `events`. That table decodes JSON escapes in a
      property value. `flag_evaluations` returns the escaped text, so a filter on such a value selects different
      rows in the two tables.
    - A query keeps reading `events` when it reads a property from a different kind of column there, such as a
      materialized column. See `_swap_reads_properties_alike`.

    The resolver inlines a saved view's body, so the swap never sees a scan inside one. Once `events` gets no flag
    calls, a query that reads a view whose body reads only flag calls from `events` raises.
    """
    database = context.database
    if (
        not context.rewrite_flag_calls_to_flag_evaluations
        or database is None
        or not database.read_flag_calls_from_flag_evaluations
    ):
        return resolve(node)
    only_in_flag_evaluations = database.flag_calls_only_in_flag_evaluations
    resolved = _resolve_with_swaps(node, context, resolve, database, only_in_flag_evaluations)
    if only_in_flag_evaluations:
        view_name = _view_reading_flag_calls_from_events(resolved)
        if view_name is not None:
            raise _flag_calls_only_in_flag_evaluations_error(
                f"it reads the saved view {view_name}, which reads them from events"
            )
    return resolved


def _resolve_with_swaps(
    node: _T_AST,
    context: HogQLContext,
    resolve: Callable[[_T_AST], _T_AST],
    database: "Database",
    only_in_flag_evaluations: bool,
) -> _T_AST:
    if not names_flag_called_event(node):
        return resolve(node)
    if not only_in_flag_evaluations and context.uses_new_events_schema():
        return resolve(node)
    with context.timings.measure("flag_calls_from_flag_evaluations"):
        rewritten = clone_expr(node)
        swapper = _EventsScanSwapper(
            now=datetime.now(UTC),
            timezone=ZoneInfo(database.get_timezone()),
            only_in_flag_evaluations=only_in_flag_evaluations,
            # The lookup reads Postgres, so it runs only when a scan pins `$feature_flag`.
            flag_key_compares_as_string=cache(partial(_flag_key_compares_as_string, context)),
        )
        swapper.visit(rewritten)
    if swapper.refusals:
        if only_in_flag_evaluations:
            raise _flag_calls_only_in_flag_evaluations_error(swapper.refusals[0])
        logger.info("flag_calls_swap_declined", team_id=context.team_id, reason=swapper.refusals[0])
    original = resolve(node)
    if not swapper.swapped:
        return original
    try:
        swapped = resolve(rewritten)
    except BaseHogQLError as error:
        # Expected for a query that reads a field flag_evaluations lacks, such as goe_0.properties.
        reason = f"it reads something that table doesn't have: {error}"
    else:
        if not _swap_keeps_bindings(original, swapped, swapper.flag_key_predicates):
            reason = "a name in it would read a different column there"
        elif not only_in_flag_evaluations and not _swap_reads_properties_alike(original, swapped, context):
            reason = "it reads a property from a different kind of column there"
        else:
            return swapped
    if only_in_flag_evaluations:
        # events gets no new flag calls, so the original query would return only calls from before the move.
        raise _flag_calls_only_in_flag_evaluations_error(reason)
    logger.info("flag_calls_swap_declined", team_id=context.team_id, reason=reason)
    return original


def _flag_key_compares_as_string(context: HogQLContext) -> bool:
    """Whether `properties.$feature_flag` compares as a string. The printer converts a property that the team's
    property definitions type as Boolean, Numeric or DateTime before it compares the value."""
    if context.team_id is None:
        return True
    metadata = load_property_metadata(
        context, event_property_names={_FLAG_KEY_PROPERTY}, person_property_names=set(), group_property_names={}
    )
    return metadata.event_properties.get(_FLAG_KEY_PROPERTY, {}).get("type") in (None, "String")


def _flag_calls_only_in_flag_evaluations_error(reason: str) -> QueryError:
    return QueryError(
        f"Your organization's {FLAG_CALLED_EVENT} events are only in posthog.flag_evaluations, and this query "
        f"can't read them there because {reason}. Change that part of the query, or query "
        "posthog.flag_evaluations directly."
    )


def _qualifies(
    scan: "EventsScan",
    node: ast.SelectQuery,
    conjuncts: list[ast.Expr],
    now: datetime,
    timezone: ZoneInfo,
    *,
    only_in_flag_evaluations: bool,
) -> bool:
    if scan.shape_refusal(node) is not None:
        return False
    if only_in_flag_evaluations:
        return scan.pins_flag_calls(conjuncts, needs_flag_key=False)
    return scan.pins_flag_calls(conjuncts, needs_flag_key=True) and scan.bounds_timestamp(conjuncts, now, timezone)


class EventsScan:
    def __init__(
        self,
        join: ast.JoinExpr,
        alias: str,
        has_other_sources: bool,
        flag_key_compares_as_string: Callable[[], bool],
    ):
        self.join = join
        self.alias = alias
        self.has_other_sources = has_other_sources
        self.flag_key_compares_as_string = flag_key_compares_as_string
        self.shadowed: frozenset[str] = frozenset()

    @classmethod
    def of(cls, node: ast.SelectQuery, flag_key_compares_as_string: Callable[[], bool]) -> "EventsScan | None":
        join = node.select_from
        if join is None or not isinstance(join.table, ast.Field) or join.table.chain != ["events"]:
            return None
        scan = cls(
            join=join,
            alias=join.alias or "events",
            # A field without a table prefix can bind to a joined table or an ARRAY JOIN alias instead.
            has_other_sources=join.next_join is not None or bool(node.array_join_list),
            flag_key_compares_as_string=flag_key_compares_as_string,
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
        # The resolver wraps each field it resolves in a hidden alias, which the check of a resolved view body sees.
        while isinstance(expr, ast.Alias) and expr.hidden:
            expr = expr.expr
        if not isinstance(expr, ast.Field) or not expr.chain:
            return None
        if expr.chain[0] == self.alias and len(expr.chain) > 1:
            return expr.chain[1:]
        if self.has_other_sources or expr.chain[0] in self.shadowed:
            return None
        return expr.chain

    def shape_refusal(self, node: ast.SelectQuery) -> str | None:
        """Why `flag_evaluations` cannot stand in for this scan whatever its filters say, or None."""
        if self.join.table_args is not None or self.join.table_final:
            return "it uses FINAL or table arguments on events"
        if self.join.column_aliases:
            return "it names the events columns with column aliases"
        if self.join.sample is not None and not self.join.sample.samples_all_rows():
            return "it uses SAMPLE"
        for item in node.select:
            while isinstance(item, ast.Alias):
                item = item.expr
            if isinstance(item, ast.ColumnsExpr) or (isinstance(item, ast.Field) and item.chain[-1:] == ["*"]):
                return "it selects * or COLUMNS(...)"
        return None

    def pins_flag_calls(self, conjuncts: list[ast.Expr], needs_flag_key: bool) -> bool:
        """Whether `conjuncts` pin `event` to flag calls. With `needs_flag_key`, a pin of `event` counts only where
        these conjuncts also pin `$feature_flag`. The recursion into `OR` branches passes False once an enclosing
        conjunct pins `$feature_flag`."""
        needs_flag_key = needs_flag_key and not self.flag_keys(conjuncts)
        return any(self._pins_flag_calls_in(conjunct, needs_flag_key) for conjunct in conjuncts)

    def _pins_flag_calls_in(self, expr: ast.Expr, needs_flag_key: bool) -> bool:
        if _pinned_values(expr, self._reads_event, _is_flag_called) is not None:
            return not needs_flag_key
        if branches := boolean_operands(expr, ast.Or):
            return all(self.pins_flag_calls(_conjuncts(branch), needs_flag_key) for branch in branches)
        return False

    def _flag_keys_in(self, expr: ast.Expr) -> list[str] | None:
        """The keys `expr` pins `$feature_flag` to, or None when it does not pin it."""
        values = _pinned_values(expr, self._reads_flag_key, _is_flag_key)
        if values is not None:
            return [value.value for value in values if isinstance(value, ast.Constant)]
        if branches := boolean_operands(expr, ast.Or):
            branch_keys = [self._flag_keys_in(branch) for branch in branches]
            if all(keys is not None for keys in branch_keys):
                return [key for keys in branch_keys if keys is not None for key in keys]
        for conjunct in boolean_operands(expr, ast.And) or []:
            keys = self._flag_keys_in(conjunct)
            if keys is not None:
                return keys
        return None

    def flag_keys(self, conjuncts: list[ast.Expr]) -> list[str]:
        """The keys a top-level conjunct pins `$feature_flag` to, or an empty list when no top-level conjunct does."""
        for conjunct in conjuncts:
            keys = self._flag_keys_in(conjunct)
            if keys is not None:
                return keys if self.flag_key_compares_as_string() else []
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
        comparison = comparison_of(expr)
        if comparison is None:
            return None
        if comparison.op in (ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Gt) and self._reads_timestamp(
            comparison.left
        ):
            return comparison.right
        if comparison.op in (ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Lt) and self._reads_timestamp(
            comparison.right
        ):
            return comparison.left
        return None

    def _reads_timestamp(self, expr: ast.Expr) -> bool:
        return self.column(expr) == ["timestamp"]


def comparison_of(expr: ast.Expr) -> ast.CompareOperation | None:
    """`expr` as a comparison, whether it is written `a >= b` or `greaterOrEquals(a, b)`."""
    if isinstance(expr, ast.CompareOperation):
        return expr
    if isinstance(expr, ast.Call) and expr.name in HOGQL_COMPARISON_MAPPING and len(expr.args) == 2:
        return ast.CompareOperation(op=HOGQL_COMPARISON_MAPPING[expr.name], left=expr.args[0], right=expr.args[1])
    return None


def compared_values(expr: ast.Expr, reads: _Predicate) -> list[ast.Expr] | None:
    """The values that `expr` compares a read matching `reads` with by `=` or `IN`, or None."""
    comparison = comparison_of(expr)
    if comparison is None:
        return None
    if comparison.op == ast.CompareOperationOp.Eq:
        if reads(comparison.left):
            return [comparison.right]
        return [comparison.left] if reads(comparison.right) else None
    if comparison.op in (ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn) and reads(comparison.left):
        right = comparison.right
        return right.exprs if isinstance(right, (ast.Tuple, ast.Array)) else [right]
    return None


def _pinned_values(expr: ast.Expr, reads: _Predicate, accepts: _Predicate) -> list[ast.Expr] | None:
    """The values `expr` limits what `reads` matches to, or None when they are not all values `accepts` matches."""
    values = compared_values(expr, reads)
    return values if values and all(accepts(value) for value in values) else None


def flag_key_predicate(table: str, keys: list[str]) -> ast.Expr | None:
    """`flag_key IN keys` on `table`, or None when a pin of `$feature_flag` to `keys` does not imply it.

    flag_key holds the key's JSON text, and a JSONExtractString pin compares the decoded key. The pin implies this
    predicate only when the JSON text of each key is the key itself.
    """
    if not keys or not all(is_json_verbatim(key) for key in keys):
        return None
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=[table, "flag_key"]),
        right=ast.Tuple(exprs=[ast.Constant(value=key) for key in keys]),
    )


def point_scan_at(
    node: ast.SelectQuery, scan: EventsScan, chain: list[str | int], condition: ast.Expr | None = None
) -> None:
    """Points `scan` at the table `chain` names, and moves the PREWHERE of `node`, with `condition`, into its WHERE.

    The new table can read person columns through a join that the printer adds later, and ClickHouse rejects a
    PREWHERE that reads a joined column. WHERE selects the same rows.
    """
    # The old alias keeps qualified reads such as `events.timestamp` resolving.
    scan.join.alias = scan.alias
    scan.join.table = ast.Field(chain=chain)
    node.where = and_conditions([node.prewhere, node.where, condition])
    node.prewhere = None


def and_conditions(conditions: list[ast.Expr | None]) -> ast.Expr | None:
    present = [condition for condition in conditions if condition is not None]
    if not present:
        return None
    return present[0] if len(present) == 1 else ast.And(exprs=present)


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


def _conjuncts(expr: ast.Expr | None) -> list[ast.Expr]:
    return top_level_conjuncts(expr) if expr is not None else []


def filter_conjuncts(node: ast.SelectQuery) -> list[ast.Expr]:
    """The top-level conjuncts of the WHERE and PREWHERE of `node`."""
    return _conjuncts(node.where) + _conjuncts(node.prewhere)


def _utc_midnight(now: datetime) -> datetime:
    return start_of_day(now.astimezone(UTC))


def names_flag_called_event(node: ast.AST) -> bool:
    """Whether `$feature_flag_called` appears as a constant anywhere in `node`."""
    finder = _FlagCalledConstantFinder()
    finder.visit(node)
    return finder.found


def boolean_operands(expr: ast.Expr, operator: type[ast.And] | type[ast.Or]) -> list[ast.Expr] | None:
    """The operands of an AND or an OR, in its node or its call form, or None for any other expression."""
    if isinstance(expr, operator):
        return expr.exprs
    if isinstance(expr, ast.Call) and expr.name == ("and" if operator is ast.And else "or"):
        return expr.args
    return None


def _earliest_instant(expr: ast.Expr, now: datetime, timezone: ZoneInfo) -> datetime | None:
    """An instant no later than the value of `expr`, or None when `expr` has a shape this cannot evaluate."""
    if isinstance(expr, ast.Constant):
        # The printer prints a naive datetime in the server's zone, which is UTC. A bare string compares in UTC or
        # in the team's zone.
        return _constant_instant(expr.value, (timezone, UTC))
    shift = _shift(expr)
    if shift is not None:
        return _shifted(_earliest_instant(shift.base, now, timezone), shift.interval, shift.sign)
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
    if (name in _START_OF_UNITS and args) or (name == "toStartOfInterval" and len(args) >= 2):
        # Evaluating the value once keeps nested rounding linear. Each rounding call would otherwise evaluate its
        # value twice, and the work would double at each level.
        instant = _earliest_instant(args[0], now, timezone)
        if instant is None:
            return None
        day_start = _start_of_day(expr, instant, timezone)
        if day_start is not None:
            return day_start
        return _rounded_down(instant, (1, _START_OF_UNITS[name]) if name in _START_OF_UNITS else _interval(args[1]))
    return None


def _start_of_day(expr: ast.Call, instant: datetime, timezone: ZoneInfo) -> datetime | None:
    """The exact start of the day `toStartOfDay(x)` or `toStartOfInterval(x, toIntervalDay(1))` rounds to, given
    `instant`, the earliest value of `x`. None for any other call or when the zone it rounds in is unknown."""
    if expr.name == "toStartOfDay" and expr.args:
        zone_index = 1
    elif expr.name == "toStartOfInterval" and len(expr.args) >= 2 and _interval(expr.args[1]) == (1, "Day"):
        zone_index = 2
    else:
        return None
    value = expr.args[0]
    # ClickHouse rounds in the zone argument, or else in the zone of the value.
    zones = _zone(expr.args[zone_index]) if len(expr.args) > zone_index else _zones_of(value, timezone)
    if not zones:
        return None
    return min(start_of_day(instant.astimezone(zone)) for zone in zones)


def _zones_of(expr: ast.Expr, timezone: ZoneInfo) -> tuple[tzinfo, ...]:
    """The zones a time value can carry. Empty when it names a zone that does not parse."""
    while True:
        shift = _shift(expr)
        if shift is not None:
            expr = shift.base
        elif isinstance(expr, ast.Call) and expr.name == "assumeNotNull" and len(expr.args) == 1:
            expr = expr.args[0]
        else:
            break
    if isinstance(expr, ast.Call):
        meta = find_hogql_function(expr.name)
        if meta is not None and meta.tz_aware and meta.max_args:
            # The printer adds the team's zone as the last argument to each timezone-aware call that names none.
            zone_index = meta.max_args - 1
            return _zone(expr.args[zone_index]) if len(expr.args) > zone_index else (timezone,)
    return (timezone, UTC)


def _zone(expr: ast.Expr) -> tuple[tzinfo, ...]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        try:
            return (ZoneInfo(expr.value),)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ()


@frozen
class _Shift:
    base: ast.Expr
    interval: tuple[int, str] | None
    sign: int


def _shift(expr: ast.Expr) -> _Shift | None:
    """`expr` as a base, an interval and a sign when it adds an interval to a time or subtracts one."""
    if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
        ast.ArithmeticOperationOp.Add,
        ast.ArithmeticOperationOp.Sub,
    ):
        sign = 1 if expr.op == ast.ArithmeticOperationOp.Add else -1
        return _Shift(base=expr.left, interval=_interval(expr.right), sign=sign)
    if not isinstance(expr, ast.Call) or len(expr.args) != 2:
        return None
    if expr.name in ("plus", "minus"):
        return _Shift(base=expr.args[0], interval=_interval(expr.args[1]), sign=1 if expr.name == "plus" else -1)
    if expr.name in _SHIFT_FUNCTIONS and (count := _integer(expr.args[1])) is not None:
        sign, unit = _SHIFT_FUNCTIONS[expr.name]
        return _Shift(base=expr.args[0], interval=(count, unit), sign=sign)
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


def _rounded_down(instant: datetime | None, interval: tuple[int, str] | None) -> datetime | None:
    """The earliest instant that rounding `instant` down to a multiple of `interval` can give."""
    rounded = _shifted(instant, interval, -1)
    if rounded is not None and interval is not None and interval[1] in _DATE_UNITS:
        return rounded - _MAX_UTC_OFFSET
    return rounded


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


class SyntaxVisitor(TraversingVisitor):
    def visit_field(self, node: ast.Field) -> None:
        # The inherited visit follows the field's type into shared CTE types, which takes exponential time. An
        # earlier step can resolve parts of the tree in place.
        pass


class _AliasCollector(SyntaxVisitor):
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


class _FlagCalledConstantFinder(SyntaxVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_constant(self, node: ast.Constant) -> None:
        if node.value == FLAG_CALLED_EVENT:
            self.found = True


class ScanVisitor(SyntaxVisitor):
    """Calls `visit_scan_query` for each SELECT whose `FROM events` can read the events table, not a CTE."""

    def __init__(self) -> None:
        super().__init__()
        # The CTE names in scope, under the resolver's rules. A `FROM events` reads a CTE when one is named `events`.
        # A name missing here lets a subclass change the scan, and the binding check then rejects the change.
        self.ctes: frozenset[str] = frozenset()

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        outer = self.ctes
        initial = node.initial_select_query
        self.visit(initial)
        # The resolver gives every later branch the first branch's WITH.
        if isinstance(initial, ast.SelectQuery) and initial.ctes:
            self.ctes = self.ctes.union(initial.ctes)
        for subsequent in node.subsequent_select_queries:
            self.visit(subsequent.select_query)
        self.ctes = outer

    def visit_cte(self, node: ast.CTE) -> None:
        # visit_select_query visits each CTE body while only the earlier CTE names are in scope.
        pass

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        outer = self.ctes
        for cte in (node.ctes or {}).values():
            self.visit(cte.expr)
            self.ctes = self.ctes.union([cte.name])
        if "events" not in self.ctes:
            self.visit_scan_query(node)
        super().visit_select_query(node)
        self.ctes = outer

    def visit_scan_query(self, node: ast.SelectQuery) -> None:
        raise NotImplementedError


class _EventsScanSwapper(ScanVisitor):
    def __init__(
        self,
        now: datetime,
        timezone: ZoneInfo,
        only_in_flag_evaluations: bool,
        flag_key_compares_as_string: Callable[[], bool],
    ) -> None:
        super().__init__()
        self.now = now
        self.timezone = timezone
        self.only_in_flag_evaluations = only_in_flag_evaluations
        self.flag_key_compares_as_string = flag_key_compares_as_string
        self.swapped = False
        self.flag_key_predicates = 0
        # Why each scan that reads only flag calls has a shape that flag_evaluations cannot stand in for.
        self.refusals: list[str] = []

    def visit_scan_query(self, node: ast.SelectQuery) -> None:
        scan = EventsScan.of(node, self.flag_key_compares_as_string)
        if scan is None:
            return
        conjuncts = filter_conjuncts(node)
        if _qualifies(
            scan, node, conjuncts, self.now, self.timezone, only_in_flag_evaluations=self.only_in_flag_evaluations
        ):
            self._swap(node, scan, conjuncts)
        else:
            refusal = scan.shape_refusal(node)
            if refusal is not None and scan.pins_flag_calls(conjuncts, needs_flag_key=False):
                self.refusals.append(refusal)

    def _swap(self, node: ast.SelectQuery, scan: EventsScan, conjuncts: list[ast.Expr]) -> None:
        # flag_key sorts the table, so this predicate lets ClickHouse skip other flags.
        flag_key = flag_key_predicate(scan.alias, scan.flag_keys(conjuncts))
        if flag_key is not None:
            self.flag_key_predicates += 1
        point_scan_at(node, scan, ["posthog", "flag_evaluations"], flag_key)
        self.swapped = True


def _swap_keeps_bindings(original: ast.AST, swapped: ast.AST, flag_key_predicates: int) -> bool:
    """Whether every field and table in the resolved swapped query binds as it does in the resolved original.

    The swap may change only the table each swapped scan reads. A name that binds elsewhere changes the result
    with no resolution error: a `WITH` name that a `flag_evaluations` column now shadows, a `COLUMNS(...)` that
    expands to other columns, or a `person_id` that read the stored events column and now reads the person overrides
    join. The persons-on-events mode decides how `events` reads person fields. The comparison ignores order,
    because the swap moves `PREWHERE` into `WHERE`. The swapped query also reads flag_key once for each of the
    `flag_key_predicates` that the swap adds.
    """
    expected = Counter(_bindings(original)) + Counter({_ADDED_FLAG_KEY_READ: flag_key_predicates})
    return Counter(_bindings(swapped)) == expected


# A field records the last part of its chain, so `e.person_id` and `person_id` match.
_Binding = tuple[str, str | int, tuple[str, ...]]

# events has no flag_key column, so the original query records this binding only for a select alias named flag_key
# that reads the scan.
_ADDED_FLAG_KEY_READ: _Binding = ("field", "flag_key", ("scan",))


def _bindings(node: ast.AST) -> list[_Binding]:
    collector = _BindingCollector()
    collector.visit(node)
    return collector.bindings


class _BindingCollector(SyntaxVisitor):
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
        # expansion reads count. An element stand-in reads no column. It returns what the events column holds for a
        # flag call, so it counts as a read of the scan.
        targets = sorted({target for _, _, target in _bindings(node.expr)})
        if targets == [("scan",)] or (not targets and node.alias in ELEMENT_STAND_INS):
            target: tuple[str, ...] = ("scan",)
        else:
            target = ("expression", *("/".join(read) for read in targets))
        self.bindings.append(("field", node.alias, target))

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
                ast.VirtualTableType,
            ),
        ):
            current = current.table_type
        elif isinstance(current, ast.LazyJoinType):
            # A join reads another table. The tables can define a join of the same name differently, so the
            # binding names the join recipe and what it joins on. Under PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            # events.person joins persons, while flag_evaluations.person reads the person properties stored with the
            # call. join_table can name the same table as an instance or as a string, so the binding leaves it out.
            join = current.lazy_join
            return (
                "join",
                current.field,
                join.resolver,
                json.dumps(join.resolver_params, sort_keys=True, default=str),
                ".".join(str(part) for part in join.from_field),
            )
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


def _swap_reads_properties_alike(original: ast.AST, swapped: ast.AST, context: HogQLContext) -> bool:
    """Whether each property that the swapped query reads comes from the same kind of column as in the original.

    A materialized or dmat column on `events` reads the strings "" and "null" as NULL. `flag_evaluations` reads the
    same property from the JSON blob, which returns those strings. A property-group map has the same definition on
    both tables, so reads from it agree. The swap pins `$feature_flag` to keys that are never "" or "null", so a
    read of it agrees whatever column backs it.
    """
    original_reads = _property_reads(original, context)
    swapped_reads = _property_reads(swapped, context)
    if not original_reads and not swapped_reads:
        return True
    if context.team_id is None:
        return False
    previous_metadata = context.property_metadata
    # The dmat slots come from the team's property definitions, which the printer loads only after this transform.
    context.property_metadata = load_property_metadata(
        context,
        event_property_names={name for column, name, _ in original_reads if column == "properties"},
        person_property_names=set(),
        group_property_names={},
    )
    try:
        return Counter(_property_sources(original_reads, context)) == Counter(_property_sources(swapped_reads, context))
    finally:
        context.property_metadata = previous_metadata


# The blob column, the property, and the field type that reads it.
_PropertyRead = tuple[str, str, ast.FieldType]


def _property_reads(node: ast.AST, context: HogQLContext) -> list[_PropertyRead]:
    collector = _PropertyReadCollector(context)
    collector.visit(node)
    return collector.reads


@frozen
class _PropertySource:
    column: str
    name: str
    # The column the printer reads the property from, or None for the JSON blob.
    materialized_column: str | None


def _property_sources(reads: list[_PropertyRead], context: HogQLContext) -> list[_PropertySource]:
    # Deferred: clickhouse_property_resolution imports the printer package, which imports this module.
    from posthog.hogql.transforms.clickhouse_property_resolution import (  # noqa: PLC0415
        resolve_materialized_property_source,
    )

    sources: list[_PropertySource] = []
    for column, name, field_type in reads:
        source = resolve_materialized_property_source(field_type, name, context)
        sources.append(
            _PropertySource(column=column, name=name, materialized_column=source.column if source is not None else None)
        )
    return sources


class _PropertyReadCollector(SyntaxVisitor):
    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context
        self.reads: list[_PropertyRead] = []

    def visit_field(self, node: ast.Field) -> None:
        if not isinstance(node.type, ast.PropertyType) or not node.type.chain:
            return
        field_type = node.type.field_type
        database_field = field_type.resolve_database_field(self.context)
        column = database_field.name if isinstance(database_field, DatabaseField) else field_type.name
        name = str(node.type.chain[0])
        if column == "properties" and name == _FLAG_KEY_PROPERTY:
            return
        self.reads.append((column, name, field_type))


def _view_reading_flag_calls_from_events(node: ast.AST) -> str | None:
    """The name of a saved view whose inlined body reads only flag calls from `events`, or None."""
    finder = _FlagCallViewFinder()
    finder.visit(node)
    return finder.found


class _FlagCallViewFinder(SyntaxVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.view: str | None = None
        self.found: str | None = None

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        outer = self.view
        # The resolver names the view on the body's top SELECT only, so a SELECT nested in the body inherits it.
        self.view = node.view_name or outer
        if self.view is not None and self.found is None and _reads_only_flag_calls_from_events(node):
            self.found = self.view
        super().visit_select_query(node)
        self.view = outer


def _reads_only_flag_calls_from_events(node: ast.SelectQuery) -> bool:
    scan = EventsScan.of(node, lambda: True)
    return (
        scan is not None
        and _reads_events_table(scan.join)
        and scan.pins_flag_calls(filter_conjuncts(node), needs_flag_key=False)
    )


def _reads_events_table(join: ast.JoinExpr) -> bool:
    """Whether a resolved FROM reads the events table, rather than a CTE named `events`."""
    table_type = join.type
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)
