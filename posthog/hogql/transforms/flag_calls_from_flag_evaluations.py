"""Read flag calls from `posthog.flag_evaluations` when a query asks `events` for them.

On flag_evaluations mode 2, ingestion stops writing `$feature_flag_called` to `events`. The native JSON events table
holds no flag calls on any mode, so a query that reads it reads flag calls as mode 2 does. This transform swaps a
query's `events` scan for `posthog.flag_evaluations` when `flag_evaluations` holds every row the scan selects, so
saved queries keep returning flag calls without a change. A scan spelled `posthog.events` reads the same table and
swaps the same way.

The swap runs before type resolution, so every rule here is syntactic. A shape the rules cannot classify keeps
reading `events`. When flag calls are only in flag_evaluations, a second pass finds the scans those rules miss in the
resolved query.
"""

import json
from collections import Counter
from collections.abc import Callable, Collection, Iterator
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from fractions import Fraction
from functools import partial
from math import isfinite
from typing import TYPE_CHECKING, Generic, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.events_with_flag_calls import EVENT_ROW_TABLES
from posthog.hogql.database.schema.flag_evaluations import (
    ELEMENT_STAND_INS,
    FlagEvaluationsTable,
    flag_evaluations_coverage_start,
    utc_midnight,
)
from posthog.hogql.database.schema.util.where_clause_extractor import (
    event_field_type,
    top_level_conjuncts,
    unwrap_table_alias_type,
)
from posthog.hogql.errors import BaseHogQLError, QueryError
from posthog.hogql.functions.mapping import HOGQL_COMPARISON_MAPPING, find_hogql_function
from posthog.hogql.join_sources import JoinSources
from posthog.hogql.property_metadata import PropertyMetadata, load_property_metadata
from posthog.hogql.resolver_utils import table_folds_identifier_case
from posthog.hogql.utils import is_json_verbatim
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.date_util import start_of_day

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

logger = structlog.get_logger(__name__)

_FLAG_KEY_PROPERTY = "$feature_flag"

_Predicate = Callable[[ast.Expr], bool]


class _Resolve(Protocol[_T_AST]):
    def __call__(self, node: _T_AST, /, *, join_sources: JoinSources | None = None) -> _T_AST: ...


@frozen
class FlagCallSwap(Generic[_T_AST]):
    # The unresolved tree that `resolved` came from: the input, or its copy with the swapped scans.
    source: _T_AST
    resolved: _T_AST


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

_UNMOVABLE_SHAPE = "it reads events in a shape that can't be moved to posthog.flag_evaluations yet"

# An alias with one of these names can shadow the column in an unqualified read.
_SCAN_COLUMNS = frozenset({"event", "timestamp", "properties"})

EVENTS_NAMES = frozenset({"events", "posthog.events"})


def can_read_flag_evaluations(
    node: ast.SelectQuery,
    now: datetime,
    timezone: ZoneInfo,
    *,
    only_in_flag_evaluations: bool = False,
    flag_key_compares_as_string: bool = True,
    database: "Database | None" = None,
) -> bool:
    """Whether this query's `events` scan selects only rows that `flag_evaluations` holds.

    It holds when all of these hold:

    1. A top-level conjunct pins the scan's `event` to `$feature_flag_called`. A name without a table prefix reads
       the scan unless a select alias shadows it or, in a chain of two or more parts, its head names another
       source in FROM.
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
    binds as it did before, and every field that starts with `posthog.events` reads the scan.
    """
    scan = EventsScan.of(node, lambda: flag_key_compares_as_string, node.ctes or {}, database)
    return scan is not None and _qualifies(
        scan, node, filter_conjuncts(node), now, timezone, only_in_flag_evaluations=only_in_flag_evaluations
    )


def swaps_flag_calls(node: ast.AST, context: HogQLContext) -> bool:
    """Whether `resolve_flag_calls_from_flag_evaluations` can change where `node` reads flag calls from. It reads
    only the context and the text of `node`, and it resolves nothing."""
    return _swap_database(context) is not None and names_flag_called_event(node)


def _swap_database(context: HogQLContext) -> "Database | None":
    """The database when the context allows the swap, or None."""
    if not context.rewrite_flag_calls_to_flag_evaluations or not context.reads_flag_calls_from_flag_evaluations():
        return None
    return context.database


def resolve_flag_calls_from_flag_evaluations(node: _T_AST, context: HogQLContext, resolve: _Resolve[_T_AST]) -> _T_AST:
    """`node` resolved with `resolve`, with each `events` scan that `swap_flag_calls` accepts reading
    `posthog.flag_evaluations` instead."""
    return swap_flag_calls(node, context, resolve).resolved


def swap_flag_calls(
    node: _T_AST, context: HogQLContext, resolve: _Resolve[_T_AST], *, view_name: str | None = None
) -> FlagCallSwap[_T_AST]:
    """`node` resolved with `resolve`, with each `events` scan that `can_read_flag_evaluations` accepts reading
    `posthog.flag_evaluations` instead. When the flag-call union is on, each other scan that reads flag calls with
    other events reads `posthog.events_with_flag_calls`, as `read_flag_calls_with_union` decides.

    This returns the changed query only when it resolves, every name in it binds as it does in the original, and
    every field in it that starts with `posthog.events` reads a scan.
    Otherwise it returns the resolved original. When the query's flag calls are only in `flag_evaluations`, as on
    mode 2 or on the native JSON events table, it raises a QueryError instead of returning the original. It also
    raises before it resolves anything when such a query has a scan of only flag calls with a shape that
    `flag_evaluations` cannot stand in for. When the union refuses a scan, the query raises only if that scan still
    reads `events` after `swap_scans_found_by_type`.

    While `events` still gets flag calls, the original query is the answer when it reads a property from a different
    kind of column there, such as a materialized column. See `_swap_reads_properties_alike`. A project that reads the
    native JSON events table always reads flag calls from `flag_evaluations`, because that table holds none. The
    native table decodes JSON escapes in a property value and `flag_evaluations` returns the escaped text, so a
    filter on such a value can select different rows than the same filter on other events.

    When the query's flag calls are only in `flag_evaluations`, a scan that the syntactic rules miss swaps
    too when the resolved original shows that its filters pin `event` to flag calls in its WHERE or PREWHERE. The
    query raises when such a scan cannot swap. A scan that the resolver adds, such as one in an inline cohort, is not
    swapped here. On mode 2 with the union enabled, `read_flag_calls_in_inline_cohort` points an inline cohort's scans
    at the union. Otherwise they read `events`.

    The resolver runs this on the body of each saved view that it inlines, and `view_name` names that view for the
    error. The check of resolved filters skips the joins of a view's body in the enclosing query, because the swap of
    that body already checked them. A top-level query raises when it reads a view whose resolved body still reads
    only flag calls from `events`, such as a body that filters with `matchesAction`.
    """
    # Deferred: flag_calls_union imports this module.
    from posthog.hogql.transforms.flag_calls_union import refuse_union_table_by_name  # noqa: PLC0415

    refuse_union_table_by_name(node, context)
    database = _swap_database(context)
    if database is None:
        return FlagCallSwap(source=node, resolved=resolve(node))
    node = _flag_called_lists_as_arrays(node)
    if names_flag_called_event(node):
        swap = _resolve_with_swaps(node, context, resolve, database, view_name)
    else:
        swap = FlagCallSwap(
            source=node,
            resolved=_without_unreadable_inline_cohort_scans(resolve(node), context, view_name),
        )
    # A view's body names flag calls only after resolution when it filters with `matchesAction`, so its swap never
    # runs. The check reads the whole resolved query, so it runs once, for the top-level query.
    if context.flag_calls_only_in_flag_evaluations() and view_name is None:
        unswapped_view = _view_reading_flag_calls_from_events(swap.resolved)
        if unswapped_view is not None:
            raise flag_calls_only_in_flag_evaluations_error(
                f"it reads the saved view {unswapped_view}, which reads them from events", None
            )
    return swap


def _resolve_with_swaps(
    node: _T_AST, context: HogQLContext, resolve: _Resolve[_T_AST], database: "Database", view_name: str | None
) -> FlagCallSwap[_T_AST]:
    only_in_flag_evaluations = context.flag_calls_only_in_flag_evaluations()
    # Deferred: flag_calls_union imports this module.
    from posthog.hogql.transforms.flag_calls_union import (  # noqa: PLC0415
        read_flag_calls_with_union,
        union_applies,
        union_unreadable_reason,
    )

    with context.timings.measure("flag_calls_from_flag_evaluations"):
        # The lookup reads Postgres, so it runs only when a scan pins `$feature_flag`.
        compares_as_string = partial(team_flag_key_compares_as_string, context)
        rewritten = clone_expr(node)
        clones = _join_clones(node, rewritten) if only_in_flag_evaluations else {}
        swapper = _EventsScanSwapper(
            now=datetime.now(UTC),
            timezone=ZoneInfo(database.get_timezone()),
            only_in_flag_evaluations=only_in_flag_evaluations,
            flag_key_compares_as_string=compares_as_string,
            union_reads_ratio_samples=only_in_flag_evaluations and union_applies(context),
            database=database,
        )
        swapper.visit(rewritten)
        union = read_flag_calls_with_union(rewritten, context, compares_as_string)
    if only_in_flag_evaluations and swapper.refusals:
        raise flag_calls_only_in_flag_evaluations_error(swapper.refusals[0], view_name)
    if not only_in_flag_evaluations and (swapper.refusals or union.refusals):
        reason = swapper.refusals[0] if swapper.refusals else union.refusals[0].reason
        logger.info("flag_calls_swap_declined", team_id=context.team_id, reason=reason)
    sources = JoinSources() if only_in_flag_evaluations else None
    original = resolve(node, join_sources=sources)
    if sources is not None:
        with context.timings.measure("flag_calls_from_flag_evaluations_by_type"):
            refusal = swapper.swap_scans_found_by_type(original, sources, clones)
        # swap_scans_found_by_type can move a scan that the union refused, such as a scan joined after another table,
        # to flag_evaluations. Each other refused scan still reads flag calls from events.
        refusal = refusal or next(
            (
                union_refusal.reason
                for union_refusal in union.refusals
                if _table_chain(union_refusal.join) != ["posthog", "flag_evaluations"]
            ),
            None,
        )
        if refusal is not None:
            raise flag_calls_only_in_flag_evaluations_error(refusal, view_name)
    if not swapper.swapped and not union.renamed:
        return FlagCallSwap(
            source=node,
            resolved=_without_unreadable_inline_cohort_scans(original, context, view_name),
        )
    try:
        swapped = resolve(rewritten)
    except BaseHogQLError as error:
        # Expected for a query that reads a field flag_evaluations lacks, such as goe_0.properties.
        reason = f"it reads something that table doesn't have: {error}"
    else:
        # An inline cohort renames its own scans during resolution, so the outer rename does not show them.
        unreadable = union_unreadable_reason(swapped, context) if union.renamed or only_in_flag_evaluations else None
        if unreadable is not None:
            reason = unreadable
        elif not _swap_keeps_bindings(original, swapped, swapper.flag_key_predicates):
            reason = "a name in it would read a different column there"
        elif not _posthog_events_qualifiers_read_scans(swapped):
            reason = "a name in it that starts with posthog.events reads another table"
        elif not only_in_flag_evaluations and not _swap_reads_properties_alike(original, swapped, context):
            reason = "it reads a property from a different kind of column there"
        else:
            # A view body's offsets come from the view's own text, not from the query the editor shows.
            if view_name is None:
                context.flag_called_union_spans.update(union.literal_spans)
            if swapper.swapped:
                context.flag_calls_read.add("flag_evaluations")
            return FlagCallSwap(source=rewritten, resolved=swapped)
    if only_in_flag_evaluations:
        # events gets no new flag calls, so the original query would return only calls from before the move.
        raise flag_calls_only_in_flag_evaluations_error(reason, view_name)
    logger.info("flag_calls_swap_declined", team_id=context.team_id, reason=reason)
    return FlagCallSwap(source=node, resolved=original)


def _without_unreadable_inline_cohort_scans(resolved: _T_AST, context: HogQLContext, view_name: str | None) -> _T_AST:
    # Deferred: flag_calls_union imports this module.
    from posthog.hogql.transforms.flag_calls_union import require_union_readable  # noqa: PLC0415

    require_union_readable(resolved, context, view_name)
    return resolved


def team_flag_key_compares_as_string(context: HogQLContext) -> bool:
    if context.team_id is None:
        return True
    return flag_key_typed_as_string(_event_property_metadata(context, {_FLAG_KEY_PROPERTY}))


def flag_key_typed_as_string(metadata: PropertyMetadata | None) -> bool:
    """Whether `properties.$feature_flag` compares as a string under the property types in `metadata`. The printer
    converts a property that the team's property definitions type as Boolean, Numeric or DateTime before it compares
    the value."""
    return metadata is None or metadata.event_properties.get(_FLAG_KEY_PROPERTY, {}).get("type") in (None, "String")


@frozen
class FlagCallPropertyMetadata:
    names: frozenset[str]
    metadata: PropertyMetadata


def _event_property_metadata(context: HogQLContext, names: set[str]) -> PropertyMetadata:
    """The definitions of event properties `names`, and of every event property this query loaded before them."""
    cached = context.flag_call_property_metadata
    loaded_names = cached.names if cached is not None else frozenset()
    missing = names - loaded_names
    if cached is not None and not missing:
        return cached.metadata
    loaded = load_property_metadata(
        context, event_property_names=missing, person_property_names=set(), group_property_names={}
    )
    if cached is not None:
        loaded = PropertyMetadata(
            event_properties={**cached.metadata.event_properties, **loaded.event_properties},
            # The registry loader caches its fetch, so keeping the first one fetches the registry once per query.
            materialized_columns=cached.metadata.materialized_columns,
        )
    context.flag_call_property_metadata = FlagCallPropertyMetadata(names=loaded_names | missing, metadata=loaded)
    return loaded


def flag_calls_only_in_flag_evaluations_error(reason: str, view_name: str | None = None) -> QueryError:
    subject, part = ("this query", "query") if view_name is None else (f"the view {view_name}", "view")
    return QueryError(
        f"Your organization's {FLAG_CALLED_EVENT} events are only in posthog.flag_evaluations, and {subject} "
        f"can't read them there because {reason}. Change that part of the {part}, or query "
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
        other_tables: frozenset[str],
        flag_key_compares_as_string: Callable[[], bool],
        qualified_only: bool = False,
        folded_tables: frozenset[str] = frozenset(),
    ):
        self.join = join
        self.alias = alias
        self.other_tables = other_tables
        self.folded_tables = folded_tables
        self.qualified_only = qualified_only
        self.flag_key_compares_as_string = flag_key_compares_as_string
        self.shadowed: frozenset[str] = frozenset()
        self.qualifier_shadows: frozenset[str] = frozenset()

    @classmethod
    def of_scan_chains(cls, flag_key_compares_as_string: Callable[[], bool]) -> "EventsScan":
        """A scan whose reads are unqualified chains, for a predicate already rewritten relative to one scan."""
        return cls(
            ast.JoinExpr(table=ast.Field(chain=["events"])),
            alias="",
            other_tables=frozenset(),
            flag_key_compares_as_string=flag_key_compares_as_string,
        )

    @classmethod
    def of(
        cls,
        node: ast.SelectQuery,
        flag_key_compares_as_string: Callable[[], bool],
        ctes: Collection[str],
        database: "Database | None" = None,
    ) -> "EventsScan | None":
        """The scan of `node`, or None when `node` does not read `events`. `ctes` holds the CTE names in scope. The
        resolver reads a CTE when one has the table's dotted name. Without `database`, no joined table counts as one
        that folds identifier case."""
        join = node.select_from
        if join is None or not isinstance(join.table, ast.Field):
            return None
        parts = [str(part) for part in join.table.chain]
        table_name = ".".join(parts)
        if table_name not in EVENTS_NAMES or table_name in ctes:
            return None
        cte_names = frozenset(ctes)
        scan = cls(
            join=join,
            alias=join.alias or "__".join(parts),
            # The resolver reads the head of a chain of two or more parts as one of these tables first.
            other_tables=cte_names.union(_join_names(join.next_join)),
            folded_tables=frozenset(_folded_join_names(join.next_join, database)),
            flag_key_compares_as_string=flag_key_compares_as_string,
        )
        aliases = select_aliases(node)
        # The resolver tries a joined table's name, a CTE and a select alias before it reads a qualifier such as
        # `posthog.events` as the name of a table.
        scan.qualifier_shadows = scan.other_tables.union(name for name, _ in aliases)
        # An alias such as `e.timestamp AS timestamp` reads the column it names, so it changes no read.
        scan.shadowed = frozenset(
            name for name, expr in aliases if name in _SCAN_COLUMNS and scan.column(expr) != [name]
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
        unqualified = self._without_dotted_qualifier(expr.chain)
        if unqualified is not None:
            return unqualified
        if self.qualified_only:
            return None
        head = str(expr.chain[0])
        if len(expr.chain) > 1 and (head in self.other_tables or head.lower() in self.folded_tables):
            return None
        # The resolver rejects a name that two sources in FROM have as ambiguous. Events has every scan column, so a
        # name that no select alias shadows reads the scan in any query that resolves.
        if head in self.shadowed:
            return None
        return expr.chain

    def _without_dotted_qualifier(self, chain: list[str | int]) -> list[str | int] | None:
        """`chain` without a leading `posthog.events`, or None when it has none. Without an alias, `FROM posthog.events`
        puts the table in scope as `posthog__events`, and a read can spell that name as `posthog.events` or
        `` `posthog.events` ``."""
        if self.alias != "posthog__events" or str(chain[0]) in self.qualifier_shadows:
            return None
        return _below_posthog_events(chain)

    def shape_refusal(self, node: ast.SelectQuery, *, ratio_sample_ok: bool = False) -> str | None:
        """Why another table cannot stand in for this scan whatever its filters say, or None. With `ratio_sample_ok`,
        a SAMPLE that `ratio_sample_fraction` reads does not count, for a table that applies the ratio itself."""
        if self.join.table_args is not None or self.join.table_final:
            return "it uses FINAL or table arguments on events"
        if self.join.column_aliases:
            return "it names the events columns with column aliases"
        sample = self.join.sample
        if sample is not None and not sample.samples_all_rows():
            if not ratio_sample_ok or ratio_sample_fraction(sample) is None:
                return "it uses SAMPLE"
        for item in node.select:
            while isinstance(item, ast.Alias):
                item = item.expr
            if isinstance(item, ast.ColumnsExpr) or (isinstance(item, ast.Field) and item.chain[-1:] == ["*"]):
                return "it selects * or COLUMNS(...)"
        return None

    def pins_flag_calls(self, conjuncts: list[ast.Expr], needs_flag_key: bool) -> bool:
        """Whether `conjuncts` pin `event` to flag calls. With `needs_flag_key`, a pin of `event` counts only where
        these conjuncts also pin `$feature_flag`."""
        return _pins_flag_calls(conjuncts, self._reads_event, self.flag_keys if needs_flag_key else None)

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
        coverage_start = flag_evaluations_coverage_start(now)
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


def _pins_flag_calls(
    conjuncts: list[ast.Expr], reads_event: _Predicate, flag_keys: Callable[[list[ast.Expr]], list[str]] | None
) -> bool:
    """Whether `conjuncts` pin what `reads_event` matches to flag calls: by `=` or `IN` of only
    `$feature_flag_called`, or by an `OR` whose every branch pins. With `flag_keys`, a pin counts only where these
    conjuncts also pin `$feature_flag`. The recursion into `OR` branches drops `flag_keys` once an enclosing
    conjunct pins `$feature_flag`."""
    if flag_keys is not None and flag_keys(conjuncts):
        flag_keys = None
    return any(_pins_flag_calls_in(conjunct, reads_event, flag_keys) for conjunct in conjuncts)


def _pins_flag_calls_in(
    expr: ast.Expr, reads_event: _Predicate, flag_keys: Callable[[list[ast.Expr]], list[str]] | None
) -> bool:
    if _pinned_values(expr, reads_event, _is_flag_called) is not None:
        return flag_keys is None
    if branches := boolean_operands(expr, ast.Or):
        return all(_pins_flag_calls(_conjuncts(branch), reads_event, flag_keys) for branch in branches)
    return False


def _join_names(join: ast.JoinExpr | None) -> Iterator[str]:
    """The name each join in the chain from `join` puts in scope. A joined subquery without an alias puts none."""
    while join is not None:
        if join.alias is not None:
            yield join.alias
        elif isinstance(join.table, ast.Field):
            yield "__".join(str(part) for part in join.table.chain)
        join = join.next_join


def _folded_join_names(join: ast.JoinExpr | None, database: "Database | None") -> Iterator[str]:
    """The lowercased name of each joined table that the resolver matches in any case."""
    while database is not None and join is not None:
        if isinstance(join.table, ast.Field):
            chain = [str(part) for part in join.table.chain]
            try:
                table = database.get_table(chain) if database.has_table(chain) else None
            except BaseHogQLError:
                table = None
            if isinstance(table, Table) and table_folds_identifier_case(table, join.alias):
                yield (join.alias or "__".join(chain)).lower()
        join = join.next_join


def _below_posthog_events(chain: list[str | int]) -> list[str | int] | None:
    """`chain` without a leading `posthog.events` or `` `posthog.events` ``, or None when it has neither."""
    if chain[0] == "posthog.events" and len(chain) > 1:
        return chain[1:]
    if chain[:2] == ["posthog", "events"] and len(chain) > 2:
        return chain[2:]
    return None


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


def ratio_sample_fraction(sample: ast.SampleExpr) -> Fraction | None:
    """The share of distinct ids that `SAMPLE k` or `SAMPLE a/b` keeps, or None for any other form.

    ClickHouse reads `SAMPLE n` with n above 1 as a row count, and `OFFSET` moves the sampled range. Neither has a
    ratio that another table could apply.
    """
    if sample.offset_value is not None:
        return None
    ratio = sample.sample_value
    constants = [ratio.left, ratio.right or ast.Constant(value=1)]
    if not all(
        isinstance(c.value, int | float)
        and not isinstance(c.value, bool)
        and (isinstance(c.value, int) or isfinite(c.value))
        for c in constants
    ):
        return None
    numerator, denominator = (Fraction(c.value if isinstance(c.value, int) else str(c.value)) for c in constants)
    fraction = numerator / denominator if denominator else None
    return fraction if fraction is not None and 0 < fraction < 1 else None


def point_scan_at(
    node: ast.SelectQuery, scan: EventsScan, chain: list[str | int], condition: ast.Expr | None = None
) -> None:
    """Points `scan` at the table `chain` names, and moves the PREWHERE of `node`, with `condition`, into its WHERE.

    The new table can read person columns through a join that the printer adds later, and ClickHouse rejects a
    PREWHERE that reads a joined column. A query that reads the union reads a subquery, which cannot have a PREWHERE.
    WHERE selects the same rows.
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


def names_flag_called_event(node: ast.AST) -> bool:
    """Whether `$feature_flag_called` appears as a constant anywhere in `node`."""
    return _has_constant(node, names_flag_called)


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
        return utc_midnight(now) - _DAY_IN_ANY_TIMEZONE
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


def select_aliases(node: ast.SelectQuery, *, in_scope_only: bool = False) -> list[tuple[str, ast.Expr]]:
    """Each alias that `node` defines outside its subqueries, with the expression it names.

    With `in_scope_only`, the list leaves out the aliases that the resolver does not register in the scope of `node`:
    an alias inside a lambda, and a hidden alias.
    """
    collector = _AliasCollector(node, in_scope_only)
    collector.visit(node)
    return collector.aliases


class _AliasCollector(SyntaxVisitor):
    def __init__(self, root: ast.SelectQuery, in_scope_only: bool) -> None:
        super().__init__()
        self.root = root
        self.in_scope_only = in_scope_only
        self.aliases: list[tuple[str, ast.Expr]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A subquery's aliases do not reach the outer scope.
        if node is self.root:
            super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_lambda(self, node: ast.Lambda) -> None:
        # The resolver registers an alias inside a lambda in the scope of that lambda.
        if not self.in_scope_only:
            super().visit_lambda(node)

    def visit_alias(self, node: ast.Alias) -> None:
        if not (self.in_scope_only and node.hidden):
            self.aliases.append((node.alias, node.expr))
        super().visit_alias(node)


class _ConstantFinder(SyntaxVisitor):
    def __init__(self, matches: Callable[[object], bool]) -> None:
        super().__init__()
        self.matches = matches
        self.found = False

    def visit_constant(self, node: ast.Constant) -> None:
        if self.matches(node.value):
            self.found = True


def _has_constant(node: ast.AST, matches: Callable[[object], bool]) -> bool:
    finder = _ConstantFinder(matches)
    finder.visit(node)
    return finder.found


def names_flag_called(value: object) -> bool:
    """Whether a constant's value is `$feature_flag_called`, or a list or tuple that holds it as an item. It does not
    look inside nested lists, because a user can supply a placeholder value nested deeper than the stack allows."""
    if isinstance(value, (list, tuple)):
        return FLAG_CALLED_EVENT in value
    return value == FLAG_CALLED_EVENT


def _is_flag_called_list(value: object) -> bool:
    return isinstance(value, (list, tuple)) and names_flag_called(value)


def _flag_called_lists_as_arrays(node: _T_AST) -> _T_AST:
    """`node` with each list or tuple constant that names `$feature_flag_called` written as an array or a tuple of
    constants. A query builder can write `event IN ['$pageview', '$feature_flag_called']` as one list constant, and
    the rules that find flag calls read only the items of an array or a tuple. Both forms match the same rows."""
    if not _has_constant(node, _is_flag_called_list):
        return node
    return _FlagCalledListExpander().visit(node)


class _FlagCalledListExpander(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)

    def visit_constant(self, node: ast.Constant) -> ast.Expr:
        if _is_flag_called_list(node.value):
            return _as_expr(node.value, node)
        return super().visit_constant(node)


def _as_expr(value: list | tuple, source: ast.Constant) -> ast.Expr:
    items = [ast.Constant(value=item, is_sensitive=source.is_sensitive) for item in value]
    container = ast.Array if isinstance(value, list) else ast.Tuple
    return container(start=source.start, end=source.end, exprs=items)


class ScanVisitor(SyntaxVisitor):
    """Calls `visit_scan_query` for each SELECT. `ctes` then holds the CTEs in scope by name, which `EventsScan.of`
    needs. A subclass reads `ctes` only during the call, because a later CTE of the same WITH changes it in place."""

    def __init__(self) -> None:
        super().__init__()
        # The CTEs in scope, under the resolver's rules. A `FROM events` reads a CTE when one is named `events`.
        # A name missing here lets a subclass change the scan, and the binding check then rejects the change.
        self.ctes: dict[str, ast.CTE] = {}

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        outer = self.ctes
        initial = node.initial_select_query
        self.visit(initial)
        # The resolver gives every later branch the first branch's WITH.
        if isinstance(initial, ast.SelectQuery) and initial.ctes:
            self.ctes = {**self.ctes, **initial.ctes}
        for subsequent in node.subsequent_select_queries:
            self.visit(subsequent.select_query)
        self.ctes = outer

    def visit_cte(self, node: ast.CTE) -> None:
        # visit_select_query visits each CTE body while only the earlier CTE names are in scope.
        pass

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        outer = self.ctes
        if node.ctes:
            # One copy per WITH keeps a long WITH linear.
            self.ctes = dict(outer)
            for cte in node.ctes.values():
                self.visit(cte.expr)
                self.ctes[cte.name] = cte
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
        database: "Database",
        union_reads_ratio_samples: bool = False,
    ) -> None:
        super().__init__()
        self.union_reads_ratio_samples = union_reads_ratio_samples
        self.database = database
        self.now = now
        self.timezone = timezone
        self.only_in_flag_evaluations = only_in_flag_evaluations
        self.flag_key_compares_as_string = flag_key_compares_as_string
        self.swapped = False
        self.flag_key_predicates = 0
        # Why each scan that reads only flag calls has a shape that flag_evaluations cannot stand in for.
        self.refusals: list[str] = []

    def visit_scan_query(self, node: ast.SelectQuery) -> None:
        scan = EventsScan.of(node, self.flag_key_compares_as_string, self.ctes, self.database)
        if scan is None:
            return
        conjuncts = filter_conjuncts(node)
        if _qualifies(
            scan, node, conjuncts, self.now, self.timezone, only_in_flag_evaluations=self.only_in_flag_evaluations
        ):
            self._swap(node, scan, conjuncts)
        else:
            # On mode 2 the union reads a scan with a ratio SAMPLE, so this refuses only the other shapes.
            refusal = scan.shape_refusal(node, ratio_sample_ok=self.union_reads_ratio_samples)
            if refusal is not None and scan.pins_flag_calls(conjuncts, needs_flag_key=False):
                self.refusals.append(refusal)

    def _swap(self, node: ast.SelectQuery, scan: EventsScan, conjuncts: list[ast.Expr]) -> None:
        # flag_key sorts the table, so this predicate lets ClickHouse skip other flags.
        flag_key = flag_key_predicate(scan.alias, scan.flag_keys(conjuncts))
        if flag_key is not None:
            self.flag_key_predicates += 1
        point_scan_at(node, scan, ["posthog", "flag_evaluations"], flag_key)
        self.swapped = True

    def swap_scans_found_by_type(self, resolved: ast.AST, sources: JoinSources, clones: "_JoinClones") -> str | None:
        """Swap each events scan in the clone whose counterpart in `resolved`, the resolved original, has a WHERE or
        PREWHERE that pins `event` to flag calls, such as a scan joined after another table. `sources` holds the
        original join of each resolved join, and `clones` holds the clones of each original join. Returns why one of
        them cannot swap, or None.

        A scan that the resolver adds, such as one in a saved view's body or an inline cohort, is not swapped here. A
        view's scan keeps reading events. On mode 2 with the union enabled, an inline cohort's scan reads the union.
        Any other scan without a clone cannot swap.
        """
        for select, join in _joins(resolved):
            if not _reads_events_table(join) or sources.is_added(join):
                continue
            if not _pins_flag_calls(filter_conjuncts(select), partial(_reads_event_of, join.type), None):
                continue
            source = sources.source_of(join)
            source_clones = clones.get(id(source), []) if source is not None else []
            # The pin check above reads the filters of one SELECT. A join that several SELECTs share cannot swap.
            if not source_clones or len({id(clone.original_select) for clone in source_clones}) > 1:
                return _UNMOVABLE_SHAPE
            # A query can hold one node in several places, such as one SELECT in two branches of a UNION. Cloning
            # copies each place apart, so one original join can have several clones, and each one has to swap.
            for clone in source_clones:
                refusal = self._swap_clone(clone)
                if refusal is not None:
                    return refusal
        return None

    def _swap_clone(self, clone: "_JoinClone") -> str | None:
        chain = _table_chain(clone.join)
        if chain in (["posthog", "flag_evaluations"], ["posthog", "events_with_flag_calls"]):
            # The syntactic rules, the union rename, or an earlier resolved join from the same source already moved it.
            return None
        if chain != ["events"]:
            return _UNMOVABLE_SHAPE
        events_scan = EventsScan(
            join=clone.join,
            alias=clone.join.alias or "events",
            # The clone is unresolved, so only a name qualified with this scan's alias can count as a read of it.
            other_tables=frozenset(),
            qualified_only=True,
            flag_key_compares_as_string=self.flag_key_compares_as_string,
        )
        refusal = events_scan.shape_refusal(clone.select)
        if refusal is not None:
            return refusal
        self._swap(clone.select, events_scan, filter_conjuncts(clone.select))
        return None


@frozen
class _JoinClone:
    # Keeps the original join alive, so no other node can take the id that keys it.
    original: ast.JoinExpr
    original_select: ast.SelectQuery
    select: ast.SelectQuery
    join: ast.JoinExpr


_JoinClones = dict[int, list[_JoinClone]]


def _join_clones(original: ast.AST, clone: ast.AST) -> _JoinClones:
    """Each join of `original`, with the `SelectQuery` and `JoinExpr` in each of its places in `clone`, a copy of it."""
    clones: _JoinClones = {}
    for (original_select, join), (clone_select, clone_join) in zip(_joins(original), _joins(clone), strict=True):
        clones.setdefault(id(join), []).append(
            _JoinClone(original=join, original_select=original_select, select=clone_select, join=clone_join)
        )
    return clones


def _table_chain(join: ast.JoinExpr) -> list[str | int] | None:
    return join.table.chain if isinstance(join.table, ast.Field) else None


def _joins(node: ast.AST) -> list[tuple[ast.SelectQuery, ast.JoinExpr]]:
    collector = _JoinCollector()
    collector.visit(node)
    return collector.joins


class _JoinCollector(SyntaxVisitor):
    """Each `JoinExpr` in a FROM chain, with the `SelectQuery` that owns it."""

    def __init__(self) -> None:
        super().__init__()
        self.joins: list[tuple[ast.SelectQuery, ast.JoinExpr]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        join = node.select_from
        while join is not None:
            self.joins.append((node, join))
            join = join.next_join
        super().visit_select_query(node)


def _reads_event_of(table_type: ast.Type | None, expr: ast.Expr) -> bool:
    """Whether resolved `expr` reads the `event` column of the scan whose type is `table_type`."""
    field_type = event_field_type(expr)
    return field_type is not None and field_type.table_type is table_type


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


def _posthog_events_qualifiers_read_scans(node: ast.AST) -> bool:
    """Whether each field that starts with `posthog.events` in the SELECT of a swapped `posthog.events` scan reads an
    events or flag_evaluations scan.

    The swap counts such a field as a read of the scan. A joined table can still take that name, for example with a
    column named `posthog`. The field then reads that table in both queries, so `_swap_keeps_bindings` does not see it.
    A field in another SELECT reads whatever it names there, and the swap does not count it.
    """
    finder = _SwappedPosthogEventsScopeFinder()
    finder.visit(node)
    return all(_reads_scan(field.type) for field in finder.fields)


def _reads_scan(current: ast.Type | None) -> bool:
    while isinstance(
        current,
        (
            ast.PropertyType,
            ast.FieldType,
            ast.FieldTraverserType,
            ast.LazyJoinType,
            ast.TableAliasType,
            ast.VirtualTableType,
        ),
    ):
        current = current.field_type if isinstance(current, ast.PropertyType) else current.table_type
    return isinstance(current, ast.TableType) and isinstance(current.table, (EventsTable, FlagEvaluationsTable))


class _SwappedPosthogEventsScopeFinder(SyntaxVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.fields: list[ast.Field] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        join = node.select_from
        if (
            join is not None
            and isinstance(join.type, ast.TableAliasType)
            and join.type.alias == "posthog__events"
            and isinstance(join.type.table_type.table, FlagEvaluationsTable)
        ):
            collector = _PosthogEventsQualifiedFieldCollector(node)
            collector.visit(node)
            self.fields.extend(collector.fields)
        super().visit_select_query(node)


class _PosthogEventsQualifiedFieldCollector(SyntaxVisitor):
    def __init__(self, root: ast.SelectQuery) -> None:
        super().__init__()
        self.root = root
        self.fields: list[ast.Field] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node is self.root:
            super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and _below_posthog_events(node.chain) is not None:
            self.fields.append(node)


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
            # binding names the join recipe and what it joins on. join_table can name the same table as an instance
            # or as a string, so the binding leaves it out.
            join = current.lazy_join
            return (
                "join",
                current.field,
                join.resolver,
                json.dumps(join.resolver_params, sort_keys=True, default=str),
                ".".join(str(part) for part in join.from_field),
            )
        elif isinstance(current, (ast.TableType, ast.LazyTableType)):
            return (
                ("scan",)
                if isinstance(current.table, EVENT_ROW_TABLES)
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
    context.property_metadata = _event_property_metadata(
        context, {name for column, name, _ in original_reads if column == "properties"}
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
    # `_reads_events_table` tells a CTE from the table by its resolved type.
    scan = EventsScan.of(node, lambda: True, frozenset())
    return (
        scan is not None
        and _reads_events_table(scan.join)
        and scan.pins_flag_calls(filter_conjuncts(node), needs_flag_key=False)
    )


def _reads_events_table(join: ast.JoinExpr) -> bool:
    """Whether a resolved FROM reads the events table, rather than a CTE named `events`."""
    table_type = unwrap_table_alias_type(join.type)
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)
