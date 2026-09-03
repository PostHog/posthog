"""Find SELECTs that read `events` in a way ClickHouse cannot prune.

The events table is sorted by (team, day, event name). A filter on the event name or a lower
timestamp bound is answered from that index. A filter on a property is not: every row in the
range is read to check it. So a SELECT that reads `events` with a property filter and no event
name filter scans its whole date range, and one with no timestamp bound scans the whole history.
"""

from collections.abc import Iterable
from enum import StrEnum
from logging import getLogger
from typing import TYPE_CHECKING

from django.db import DatabaseError

from posthog.schema import EventsScanWarning

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EVENTS_TABLE_TYPES
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

    from posthog.models import Team

logger = getLogger(__name__)

_PROPERTIES = "properties"
_EVENT = "event"
_TIMESTAMP = "timestamp"

# Comparisons on the event name that the primary index answers. Negations and pattern matches do not.
_EVENT_NAME_OPS = frozenset({ast.CompareOperationOp.Eq, ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn})
_EVENT_NAME_FUNCTIONS = frozenset({"equals", "in", "globalIn"})
# `timestamp >= x`, `timestamp = x`, `timestamp IN (...)`
_LOWER_BOUND_OPS_TIMESTAMP_LEFT = frozenset(
    {ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Eq, ast.CompareOperationOp.In}
)
# `x <= timestamp`, `x = timestamp`
_LOWER_BOUND_OPS_TIMESTAMP_RIGHT = frozenset(
    {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Eq}
)
_LOWER_BOUND_FUNCTIONS_TIMESTAMP_FIRST = frozenset({"greater", "greaterOrEquals", "equals"})
_LOWER_BOUND_FUNCTIONS_TIMESTAMP_SECOND = frozenset({"less", "lessOrEquals", "equals"})
# Wrappers ClickHouse treats as monotonic, so a bound on them still prunes by the sort key.
_MONOTONIC_TIMESTAMP_FUNCTIONS = frozenset(
    {
        "toDate",
        "toDateTime",
        "toDateTime64",
        "toStartOfDay",
        "toStartOfHour",
        "toStartOfMinute",
        "toStartOfWeek",
        "toStartOfMonth",
        "toStartOfQuarter",
        "toStartOfYear",
        "toTimeZone",
        "toUnixTimestamp",
    }
)
# Above this many event names the hint stops helping and the list stops fitting in a message.
MAX_HINTED_EVENTS = 10


class EventsScanReason(StrEnum):
    PROPERTY_FILTER_WITHOUT_EVENT = "property_filter_without_event"
    NO_TIME_BOUND = "no_time_bound"
    NO_EVENT_FILTER = "no_event_filter"


@frozen
class EventsScanFinding:
    reason: EventsScanReason
    # Offsets of the `events` reference in the query text; None when the AST was built in code
    start: int | None
    end: int | None
    # Event property names the SELECT filters on, for the "events seen with" hint
    property_names: tuple[str, ...] = ()


def find_events_scans(query: ast.SelectQuery | ast.SelectSetQuery, database: "Database") -> list[EventsScanFinding]:
    """`database` resolves table names, so `posthog.events` and the persons-on-events subtables count too."""
    visitor = _EventsScanVisitor(database)
    visitor.visit(query)
    return visitor.findings


def events_scan_warnings(query: ast.SelectQuery | ast.SelectSetQuery, database: "Database") -> list[EventsScanWarning]:
    """The findings that mean real work is being wasted, shaped for a query response's `warnings`.

    Reading every event with no filter at all is often the question being asked, so that finding
    only surfaces as an editor notice, not as a response warning.
    """
    return [
        EventsScanWarning(
            type="events_scan",
            reason=finding.reason.value,
            message=finding_message(finding),
            start=finding.start,
            end=finding.end,
        )
        for finding in find_events_scans(query, database)
        if finding.reason != EventsScanReason.NO_EVENT_FILTER
    ]


def finding_message(finding: EventsScanFinding, events_by_property: dict[str, list[str]] | None = None) -> str:
    if finding.reason == EventsScanReason.NO_TIME_BOUND:
        return (
            "This query has no timestamp bound on events, so it reads your whole event history. "
            "Add one, for example timestamp >= now() - INTERVAL 7 DAY."
        )
    if finding.reason == EventsScanReason.NO_EVENT_FILTER:
        return (
            "This query reads every event in its date range. "
            "If you only need some events, filter by event name so the database can skip the rest."
        )
    message = (
        "This query reads every event in its date range to check a property. "
        "Filter by event name first, with event = '...' or event IN (...), so the database can skip the rest."
    )
    for property_name in finding.property_names:
        events = (events_by_property or {}).get(property_name)
        if events:
            message += f" Events seen with {property_name}: {', '.join(events)}."
    return message


def finding_fix(finding: EventsScanFinding) -> str | None:
    """A `HogQLNotice.fix` in its `ai_prompt:` form: the editor offers it as a "Fix with AI" action."""
    if finding.reason == EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT:
        return (
            "ai_prompt:Add an event name filter (event = '...' or event IN (...)) to every part of this query "
            "that reads the events table with a property filter, listing only the events that carry that "
            "property, so the results stay the same."
        )
    if finding.reason == EventsScanReason.NO_TIME_BOUND:
        return (
            "ai_prompt:Add a lower timestamp bound to every part of this query that reads the events table, "
            "matching the period the question is about."
        )
    return None


def events_seen_with_properties(team: "Team", property_names: Iterable[str]) -> dict[str, list[str]]:
    """Which event names have carried each property, from the ingestion-time associations.

    Those associations are incomplete (no backfill, capped per event), so the result is a hint for
    the message, never something to rewrite a query with. Properties seen on more than
    MAX_HINTED_EVENTS events are left out: the list would not help.
    """
    from posthog.models import EventProperty  # noqa: PLC0415 - keeps the ORM off the pure AST path

    from products.event_definitions.backend.models.property_definition import effective_project_id_expr  # noqa: PLC0415

    events_by_property: dict[str, list[str]] = {}
    try:
        for property_name in dict.fromkeys(property_names):
            events = list(
                EventProperty.objects.alias(effective_project_id=effective_project_id_expr())
                .filter(effective_project_id=team.project_id, property=property_name)
                .order_by("event")
                .values_list("event", flat=True)[: MAX_HINTED_EVENTS + 1]
            )
            if 0 < len(events) <= MAX_HINTED_EVENTS:
                events_by_property[property_name] = events
    except DatabaseError:
        logger.warning("Events scan hint skipped due to a database error", exc_info=True)
        return {}
    return events_by_property


class _EventsScanVisitor(TraversingVisitor):
    def __init__(self, database: "Database") -> None:
        self.database = database
        self.findings: list[EventsScanFinding] = []
        self._cte_scopes: list[set[str]] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self._cte_scopes.append(set(node.ctes.keys()) if node.ctes else set())
        try:
            self._check(node)
            super().visit_select_query(node)
        finally:
            self._cte_scopes.pop()

    def _check(self, node: ast.SelectQuery) -> None:
        references = _events_references(node.select_from, self.database, self._cte_scopes)
        if not references:
            return
        aliases = {alias for alias, _ in references}
        first_reference = references[0][1]
        predicate = _row_predicate(node)

        has_event_filter = predicate is not None and _constrains_event(predicate, aliases)
        has_lower_bound = predicate is not None and _bounds_timestamp(predicate, aliases)
        fields = _PredicateFields.collect(predicate) if predicate is not None else _PredicateFields()

        if not has_event_filter:
            reason = (
                EventsScanReason.PROPERTY_FILTER_WITHOUT_EVENT
                if fields.references_properties
                else EventsScanReason.NO_EVENT_FILTER
            )
            self.findings.append(
                EventsScanFinding(
                    reason=reason,
                    start=first_reference.start,
                    end=first_reference.end,
                    property_names=fields.event_property_names(aliases),
                )
            )
        if not has_lower_bound:
            self.findings.append(
                EventsScanFinding(
                    reason=EventsScanReason.NO_TIME_BOUND, start=first_reference.start, end=first_reference.end
                )
            )


def _events_references(
    join: ast.JoinExpr | None, database: "Database", cte_scopes: list[set[str]]
) -> list[tuple[str, ast.Field]]:
    references: list[tuple[str, ast.Field]] = []
    while join is not None:
        if isinstance(join.table, ast.Field) and _is_events_table(join.table.chain, database, cte_scopes):
            references.append((join.alias or str(join.table.chain[-1]), join.table))
        join = join.next_join
    return references


def _is_events_table(chain: list[str | int], database: "Database", cte_scopes: list[set[str]]) -> bool:
    # `WITH events AS (...)` makes `FROM events` read the CTE, not the table
    if len(chain) == 1 and any(str(chain[0]) in scope for scope in cte_scopes):
        return False
    try:
        table = database.get_table([str(part) for part in chain])
    except Exception:
        # An unknown or inaccessible table is the resolver's error to report, not a scan
        return False
    return isinstance(table, EVENTS_TABLE_TYPES)


def _row_predicate(node: ast.SelectQuery) -> ast.Expr | None:
    parts = [part for part in (node.where, node.prewhere) if part is not None]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else ast.And(exprs=parts)


def _is_event_field(node: ast.Expr, aliases: set[str]) -> bool:
    if not isinstance(node, ast.Field):
        return False
    chain = node.chain
    return chain == [_EVENT] or (len(chain) == 2 and chain[0] in aliases and chain[1] == _EVENT)


def _is_timestamp_expr(node: ast.Expr, aliases: set[str]) -> bool:
    if isinstance(node, ast.Field):
        chain = node.chain
        return chain == [_TIMESTAMP] or (len(chain) == 2 and chain[0] in aliases and chain[1] == _TIMESTAMP)
    if isinstance(node, ast.Call) and node.name in _MONOTONIC_TIMESTAMP_FUNCTIONS and node.args:
        return _is_timestamp_expr(node.args[0], aliases)
    return False


def _constrains_event(expr: ast.Expr, aliases: set[str]) -> bool:
    """Whether the predicate pins the event name for every row it lets through."""
    match expr:
        case ast.Alias(expr=inner):
            return _constrains_event(inner, aliases)
        case ast.And(exprs=exprs):
            return any(_constrains_event(part, aliases) for part in exprs)
        case ast.Or(exprs=exprs):
            return len(exprs) > 0 and all(_constrains_event(part, aliases) for part in exprs)
        case ast.CompareOperation(op=op, left=left, right=right):
            return op in _EVENT_NAME_OPS and (_is_event_field(left, aliases) or _is_event_field(right, aliases))
        case ast.Call(name=name, args=args):
            if name in _EVENT_NAME_FUNCTIONS and len(args) == 2:
                return any(_is_event_field(arg, aliases) for arg in args)
            if name == "has" and len(args) == 2:
                return _is_event_field(args[1], aliases)
            return False
        case _:
            return False


def _bounds_timestamp(expr: ast.Expr, aliases: set[str]) -> bool:
    """Whether the predicate gives every row a lower timestamp bound the sort key can use."""
    match expr:
        case ast.Alias(expr=inner):
            return _bounds_timestamp(inner, aliases)
        case ast.And(exprs=exprs):
            return any(_bounds_timestamp(part, aliases) for part in exprs)
        case ast.Or(exprs=exprs):
            return len(exprs) > 0 and all(_bounds_timestamp(part, aliases) for part in exprs)
        case ast.CompareOperation(op=op, left=left, right=right):
            if _is_timestamp_expr(left, aliases) and op in _LOWER_BOUND_OPS_TIMESTAMP_LEFT:
                return True
            return _is_timestamp_expr(right, aliases) and op in _LOWER_BOUND_OPS_TIMESTAMP_RIGHT
        case ast.Call(name=name, args=args):
            if len(args) != 2:
                return False
            if name in _LOWER_BOUND_FUNCTIONS_TIMESTAMP_FIRST and _is_timestamp_expr(args[0], aliases):
                return True
            return name in _LOWER_BOUND_FUNCTIONS_TIMESTAMP_SECOND and _is_timestamp_expr(args[1], aliases)
        case _:
            return False


class _PredicateFields(TraversingVisitor):
    """The fields a predicate reads, without descending into subqueries, which filter their own tables."""

    def __init__(self) -> None:
        self.fields: list[ast.Field] = []
        self.array_accesses: list[ast.ArrayAccess] = []

    @classmethod
    def collect(cls, predicate: ast.Expr) -> "_PredicateFields":
        collector = cls()
        collector.visit(predicate)
        return collector

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return None

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return None

    def visit_field(self, node: ast.Field) -> None:
        self.fields.append(node)

    def visit_array_access(self, node: ast.ArrayAccess) -> None:
        self.array_accesses.append(node)
        super().visit_array_access(node)

    @property
    def references_properties(self) -> bool:
        return any(_PROPERTIES in field.chain for field in self.fields)

    def event_property_names(self, aliases: set[str]) -> tuple[str, ...]:
        names: dict[str, None] = {}
        for field in self.fields:
            chain = field.chain
            if len(chain) == 2 and chain[0] == _PROPERTIES:
                names[str(chain[1])] = None
            elif len(chain) == 3 and chain[0] in aliases and chain[1] == _PROPERTIES:
                names[str(chain[2])] = None
        for access in self.array_accesses:
            array, key = access.array, access.property
            if not isinstance(array, ast.Field) or not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            chain = array.chain
            if chain == [_PROPERTIES] or (len(chain) == 2 and chain[0] in aliases and chain[1] == _PROPERTIES):
                names[key.value] = None
        return tuple(names)
