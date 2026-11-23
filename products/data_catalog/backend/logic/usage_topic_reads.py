"""Trace the tables and views that the sessions of each topic read.

A topic title sums up the questions of its sessions. A reader who may not read a table that one of those
sessions read must not see the title, so the scan stores the tables of each topic, and a read hides only the
topics that name a table the reader is denied. When the scan cannot trace what a session read, the tables of
its topic are unknown, and a reader with any denied table does not see that topic.
"""

import re
import json
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from datetime import datetime
from typing import Any

from django.db.models import Max

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog

from products.data_tools.backend.facade.models import DataWarehouseExpression, DataWarehouseJoin
from products.product_analytics.backend.facade.models import Insight

from ..facade.enums import MARKDOWN_DEFINITION_KIND
from .agent_sessions import (
    DATA_TOOL_PREFIX,
    DATA_TOOLS,
    RUN_TOOL,
    SQL_TOOL,
    SessionText,
    decode_nested_json,
    is_data_tool,
)
from .metrics import metrics_for_team
from .usage_adjusted import paged_rows
from .validation import table_names_as_written

INSIGHT_TOOL = "insight-query"
# Text past this length counts as cut, because the part that was cut can name any table. Almost every
# query that agents send is shorter.
READ_CHARS = 20000
# The query lists piece ids in an IN clause, so it reads them in batches.
_PIECE_BATCH = 1000
# A key or a value with this marker holds a HogQL expression, which can read a table that the query does not name.
_EXPRESSION = re.compile("hogql", re.IGNORECASE)
# These run a stored cohort or action, so SQL that uses them can read a table that it does not name.
_SAVED_FILTER_FUNCTIONS = frozenset({"matchesAction", "inCohort", "notInCohort"})
_COHORT_OPERATORS = frozenset({ast.CompareOperationOp.InCohort, ast.CompareOperationOp.NotInCohort})
# Activity log entries that can change what a saved filter reads. A created row cannot have run before it existed.
_CHANGE_ACTIVITIES = ("updated", "deleted")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
# A cohort can filter on other cohorts. The scan follows that many levels, and a deeper cohort counts as unknown.
_COHORT_DEPTH = 5

# `ai_events` is ordered by trace, so trace ids come from `events`, which is ordered by time.
_READS_QUERY = """
SELECT
    toString(a.properties.$session_id) AS session,
    a.span_name,
    a.event,
    a.timestamp,
    substringUTF8(ifNull(a.input_state, ''), 1, {max_chars}) AS input,
    substringUTF8(JSONExtractString(ifNull(a.output_choices, ''), 1, 'content'), 1, {max_chars}) AS sql,
    lengthUTF8(ifNull(a.input_state, '')) > {max_chars}
        OR lengthUTF8(JSONExtractString(ifNull(a.output_choices, ''), 1, 'content')) > {max_chars} AS cut
FROM posthog.ai_events AS a
WHERE a.event IN ('$ai_span', '$ai_generation')
    AND (a.span_name IN {tools} OR startsWith(a.span_name, {tool_prefix}))
    AND a.timestamp >= {start}
    AND a.timestamp < {end}
    AND toString(a.properties.$mcp_project_uuid) = {project}
    AND toString(a.properties.$session_id) IN {sessions}
    AND a.trace_id IN (
        SELECT properties.$ai_trace_id FROM events
        WHERE event IN ('$ai_span', '$ai_generation')
            AND (properties.$ai_span_name IN {tools} OR startsWith(toString(properties.$ai_span_name), {tool_prefix}))
            AND timestamp >= {start}
            AND timestamp < {end}
            AND toString(properties.$mcp_project_uuid) = {project}
            AND toString(properties.$session_id) IN {sessions}
    )
LIMIT {row_limit}
"""


# The scan reads cohorts through HogQL, because an import of the cohorts product would close a product cycle.
_COHORTS_QUERY = """
SELECT id, is_static, filters, query FROM system.cohorts WHERE id IN {ids} LIMIT {row_limit}
"""
_COHORT_BATCH = 1000

# `$mcp_tool_call` records every call, also a call whose span the MCP server leaves out of telemetry.
_CALL_COUNTS_QUERY = """
SELECT toString(properties.$session_id) AS session, toString(properties.$mcp_tool_name) AS tool, count() AS calls
FROM events
WHERE event = '$mcp_tool_call'
    AND timestamp >= {start}
    AND timestamp < {end}
    AND toString(properties.$mcp_project_uuid) = {project}
    AND toString(properties.$session_id) IN {sessions}
    AND (toString(properties.$mcp_tool_name) IN {tools} OR startsWith(toString(properties.$mcp_tool_name), {tool_prefix}))
GROUP BY session, tool
LIMIT {row_limit}
"""


@frozen
class ReadCall:
    """One data tool call of a session piece, with its input decoded."""

    session: str
    tool: str
    event: str
    at: datetime
    payload: Any
    sql: str
    cut: bool


@frozen
class SavedDefinition:
    """A saved query, and when it last changed."""

    body: Any
    changed_at: datetime | None


@frozen
class CohortDefinition:
    """What a query that uses the cohort can run: HogQL can inline a dynamic cohort's filters into the query."""

    id: int
    is_static: bool
    filters: Any
    query: Any


@frozen
class SavedFilters:
    """What the team's saved filters read, which a query runs without naming their tables.

    ``cohorts`` says for each cohort id whether the cohort reads only PostHog's own tables.
    ``test_account_tables`` holds the tables that the test account filters read, or None when the scan
    cannot tell. The scan reads both as they are now, so the change times say which calls they still describe:
    ``cohort_changes`` holds the last change of each cohort or of a cohort that it uses."""

    cohorts: Mapping[int, bool]
    test_account_tables: frozenset[str] | None
    cohort_changes: Mapping[int, datetime] | None = None
    test_accounts_changed_at: datetime | None = None

    def as_of(self, at: datetime) -> "SavedFilters":
        """A saved filter that changed after a call can have read another table during the call."""
        changes = self.cohort_changes or {}
        return SavedFilters(
            cohorts={
                cohort_id: reads_only_posthog and not _changed_after(changes.get(cohort_id), at)
                for cohort_id, reads_only_posthog in self.cohorts.items()
            },
            test_account_tables=None if _changed_after(self.test_accounts_changed_at, at) else self.test_account_tables,
        )


def _changed_after(changed_at: datetime | None, at: datetime) -> bool:
    return changed_at is not None and changed_at > at


NO_SAVED_FILTERS = SavedFilters(cohorts={}, test_account_tables=frozenset())


@frozen
class ReadSources:
    """The saved definitions that calls read by reference: metrics by name, insights by short id.

    ``field_tables`` maps the name of each warehouse join and saved expression field to the tables that the
    field reads, or to None when the scan cannot tell. ``fields_changed_at`` holds the last change or delete of
    any of those fields."""

    metric_definitions: Mapping[str, SavedDefinition]
    insight_queries: Mapping[str, SavedDefinition]
    saved_filters: SavedFilters = NO_SAVED_FILTERS
    field_tables: Mapping[str, frozenset[str] | None] | None = None
    fields_changed_at: datetime | None = None

    def as_of(self, at: datetime) -> "ReadSources":
        """Only a definition that did not change after a call still says what that call read."""
        return ReadSources(
            metric_definitions=_unchanged(self.metric_definitions, at),
            insight_queries=_unchanged(self.insight_queries, at),
            saved_filters=self.saved_filters.as_of(at),
            field_tables=self.field_tables,
            fields_changed_at=self.fields_changed_at,
        )

    def field_reads(self, bodies: Iterable[object]) -> frozenset[str] | None:
        """A join or saved expression field reads tables that the query does not name, so its name counts.

        The match is by name only, so a field with the same name can add a table that the call did not read.
        That hides a topic that a reader could see, and never shows one that it must not."""
        if not self.field_tables:
            return frozenset()
        text = "\n".join(body if isinstance(body, str) else json.dumps(body, default=str) for body in bodies if body)
        found: set[str] = set()
        for field in set(_IDENTIFIER.findall(text)) & self.field_tables.keys():
            tables = self.field_tables[field]
            if tables is None:
                return None
            found |= tables
        return frozenset(found)


def _unchanged[K](saved: Mapping[K, SavedDefinition], at: datetime) -> dict[K, SavedDefinition]:
    return {key: item for key, item in saved.items() if item.changed_at is not None and item.changed_at <= at}


class _SavedFilterFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        self.found = self.found or node.op in _COHORT_OPERATORS
        super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call) -> None:
        self.found = self.found or node.name in _SAVED_FILTER_FUNCTIONS
        super().visit_call(node)


def sql_tables(sql: str) -> frozenset[str] | None:
    """The tables a HogQL query names, or None when it does not parse or runs a saved cohort or action.

    The check reads the parsed query, because a comment between two keywords hides them from a text match."""
    finder = _SavedFilterFinder()
    try:
        finder.visit(parse_select(sql))
        named = frozenset(table_names_as_written({"query": sql}, keep_table_functions=True))
    except (BaseHogQLError, ValidationError):
        return None
    return None if finder.found else named


def _dicts(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _reads_hidden_tables(node: dict[str, Any]) -> bool:
    """A HogQL expression or a warehouse property can read a table that the query does not name."""
    for key in ("type", "breakdown_type", "math_property_type"):
        marker = str(node.get(key) or "")
        if marker == "hogql" or marker.startswith("data_warehouse"):
            return True
    return any(_EXPRESSION.search(key) and value for key, value in node.items())


def _refers_to_action(node: dict[str, Any]) -> bool:
    """A query runs the stored steps of an action that it refers to, and their filters can read any table."""
    return (
        node.get("kind") == "ActionsNode"
        or "actions" in (node.get("type"), node.get("event_type"), node.get("seq_event_type"))
        or "actionId" in node
    )


def _cohort_ids(node: dict[str, Any]) -> list[int] | None:
    """The cohorts that a filter or a breakdown refers to, or None when one reference is not an id."""
    references = []
    if node.get("type") == "cohort":
        references.append(node.get("value"))
    if node.get("breakdown_type") == "cohort":
        references.append(node.get("breakdown"))
    ids = []
    for reference in references:
        for raw in reference if isinstance(reference, list) else [reference]:
            # A cohort breakdown names the bucket of all users "all", which is no cohort.
            if raw == "all":
                continue
            if isinstance(raw, bool) or not isinstance(raw, int | str):
                return None
            try:
                ids.append(int(raw))
            except ValueError:
                return None
    return ids


def query_tables(query: object, saved_filters: SavedFilters = NO_SAVED_FILTERS) -> frozenset[str] | None:
    """The tables that a query object reads past PostHog's own tables, or None when the scan cannot tell.

    A HogQL query names its tables, and a warehouse node names its table. An action or a cohort that the
    query uses, and the test account filters, run filters that the query does not hold. Every other node
    reads PostHog's own tables, which access control does not deny one by one."""
    if not isinstance(query, dict):
        return None
    tables: set[str] = set()
    for node in _dicts(query):
        kind = str(node.get("kind") or "")
        if kind == "HogQLQuery":
            named = sql_tables(str(node.get("query") or ""))
            if named is None:
                return None
            tables |= named
            continue
        # Funnels, lifecycle, experiments and retention each have their own node for a warehouse table.
        if kind.endswith("DataWarehouseNode") or node.get("table_name"):
            if not node.get("table_name"):
                return None
            tables.add(str(node["table_name"]))
        if _refers_to_action(node) or _reads_hidden_tables(node):
            return None
        cohort_ids = _cohort_ids(node)
        if cohort_ids is None or not all(saved_filters.cohorts.get(cohort_id, False) for cohort_id in cohort_ids):
            return None
        if node.get("filterTestAccounts") is True:
            if saved_filters.test_account_tables is None:
                return None
            tables |= saved_filters.test_account_tables
    return frozenset(tables)


def cohort_reads(cohorts: Mapping[int, CohortDefinition]) -> dict[int, bool]:
    """Whether each cohort reads only PostHog's own tables when a query inlines it.

    A static cohort runs no filters. A cohort built from a query, a cohort with a HogQL or warehouse filter,
    and a cohort that uses an action can read any table. A cohort that uses another cohort reads what that
    cohort reads, and a missing, circular or too deep reference counts as unknown."""
    verdicts: dict[int, bool] = {}

    def reads_only_posthog(cohort_id: int, path: tuple[int, ...]) -> bool:
        if cohort_id in verdicts:
            return verdicts[cohort_id]
        cohort = cohorts.get(cohort_id)
        if cohort is None or cohort_id in path or len(path) >= _COHORT_DEPTH:
            return False
        if cohort.is_static:
            verdict = True
        elif cohort.query is not None:
            verdict = False
        else:
            verdict = True
            for node in _dicts(cohort.filters):
                nested = _cohort_ids(node)
                if (
                    _refers_to_action(node)
                    or _reads_hidden_tables(node)
                    or nested is None
                    or not all(reads_only_posthog(other, (*path, cohort_id)) for other in nested)
                ):
                    verdict = False
                    break
        verdicts[cohort_id] = verdict
        return verdict

    for cohort_id in cohorts:
        reads_only_posthog(cohort_id, ())
    return verdicts


def metric_tables(
    definition: dict[str, Any] | None, saved_filters: SavedFilters = NO_SAVED_FILTERS
) -> frozenset[str] | None:
    """A stub runs no query, and a markdown metric only returns steps that the agent then runs as queries."""
    if definition is None or definition.get("kind") == MARKDOWN_DEFINITION_KIND:
        return frozenset()
    return query_tables(definition, saved_filters)


def insight_tables(
    saved: SavedDefinition | None, filters_override: object, saved_filters: SavedFilters = NO_SAVED_FILTERS
) -> frozenset[str] | None:
    """An insight run merges its filter override into the saved query, so the override's filters count too.

    A variable override only sets values, so it reads no table."""
    if saved is None:
        return None
    query = query_tables(saved.body, saved_filters)
    override = frozenset() if filters_override is None else query_tables(filters_override, saved_filters)
    return None if query is None or override is None else query | override


def _payload_field(call: ReadCall, field: str) -> str:
    value = call.payload.get(field) if isinstance(call.payload, dict) else None
    return str(value) if value else ""


def _direct_tables(call: ReadCall, current: ReadSources) -> frozenset[str] | None:
    if call.tool == SQL_TOOL:
        # A metadata search logs as a span with its query in the input, and every other query as a generation.
        sql = call.sql if call.event == "$ai_generation" else _payload_field(call, "query")
        return sql_tables(sql) if sql else None
    if call.tool == RUN_TOOL:
        metric = current.metric_definitions.get(_payload_field(call, "name"))
        return metric_tables(metric.body, current.saved_filters) if metric is not None else None
    if call.tool == INSIGHT_TOOL:
        overrides = call.payload.get("filters_override") if isinstance(call.payload, dict) else None
        insight = current.insight_queries.get(_payload_field(call, "insightId"))
        return insight_tables(insight, overrides, current.saved_filters)
    if call.tool.startswith(DATA_TOOL_PREFIX):
        # The MCP server fills an omitted `filterTestAccounts` from the project default, which the log does not
        # hold, so an omitted flag counts as set. That can only add the tables of the test account filters.
        query = call.payload
        if isinstance(query, dict) and query.get("filterTestAccounts") is None:
            query = {**query, "filterTestAccounts": True}
        return query_tables(query, current.saved_filters)
    # A dashboard run reads the insights on the dashboard as it is now, which can differ from the run.
    return None


def _call_bodies(call: ReadCall, current: ReadSources) -> list[object]:
    """Every text that a call ran: its own input, and the saved definition that it ran by name."""
    metric = current.metric_definitions.get(_payload_field(call, "name")) if call.tool == RUN_TOOL else None
    insight = current.insight_queries.get(_payload_field(call, "insightId")) if call.tool == INSIGHT_TOOL else None
    return [call.payload, call.sql, *(saved.body for saved in (metric, insight) if saved is not None)]


def call_tables(call: ReadCall, sources: ReadSources) -> frozenset[str] | None:
    """The tables that one call read, or None when the scan cannot tell."""
    if call.cut:
        return None
    # A join or expression that changed or went away after the call can have read a table that no field names now.
    if _changed_after(sources.fields_changed_at, call.at):
        return None
    current = sources.as_of(call.at)
    found = _direct_tables(call, current)
    fields = None if found is None else current.field_reads(_call_bodies(call, current))
    return None if found is None or fields is None else found | fields


def session_tables(
    calls: Iterable[ReadCall],
    tools: Collection[str],
    sources: ReadSources,
    call_counts: Mapping[str, int] | None = None,
) -> frozenset[str] | None:
    """The tables that one session read, or None when the scan cannot tell for one of its calls.

    Telemetry can lose a call, and the MCP server leaves some calls out of it, so a data tool with fewer
    logged reads than ``call_counts`` says, or with no logged read at all, also makes the answer unknown."""
    tables: set[str] = set()
    by_event: Counter[tuple[str, str]] = Counter()
    for call in calls:
        found = call_tables(call, sources)
        if found is None:
            return None
        tables |= found
        by_event[(call.tool, call.event)] += 1
    # A metadata search logs both a span and a generation, so the larger count is the number of reads.
    logged: Counter[str] = Counter()
    for (tool, _event), count in by_event.items():
        logged[tool] = max(logged[tool], count)
    expected = Counter({tool: 1 for tool in tools if is_data_tool(tool)})
    expected |= Counter({tool: count for tool, count in (call_counts or {}).items() if is_data_tool(tool)})
    if any(logged[tool] < count for tool, count in expected.items()):
        return None
    return frozenset(tables)


def topic_tables(
    session_ids: Iterable[str], tables_by_session: Mapping[str, frozenset[str] | None]
) -> list[str] | None:
    """The tables of every session in a topic, or None when one session's tables are unknown."""
    tables: set[str] = set()
    for session_id in session_ids:
        found = tables_by_session.get(session_id)
        if found is None:
            return None
        tables |= found
    return sorted(tables)


def _placeholders(piece_ids: Sequence[str]) -> dict[str, ast.Expr]:
    return {
        "tools": ast.Tuple(exprs=[ast.Constant(value=tool) for tool in DATA_TOOLS]),
        "tool_prefix": ast.Constant(value=DATA_TOOL_PREFIX),
        "sessions": ast.Tuple(exprs=[ast.Constant(value=piece) for piece in piece_ids]),
        "max_chars": ast.Constant(value=READ_CHARS),
    }


def _fetch_calls(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime, piece_ids: Sequence[str]
) -> list[ReadCall]:
    rows = paged_rows(
        _READS_QUERY,
        team,
        telemetry_team,
        window_start,
        window_end,
        "DataCatalogUsageTopicReads",
        placeholders=_placeholders(piece_ids),
    )
    return [
        ReadCall(
            session=session,
            tool=tool,
            event=event,
            at=at,
            payload=decode_nested_json(raw),
            sql=sql,
            cut=bool(cut),
        )
        for session, tool, event, at, raw, sql, cut in rows
    ]


def _fetch_call_counts(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime, piece_ids: Sequence[str]
) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    # The rows come one time page at a time, so a piece that spans pages adds up its counts.
    for session, tool, calls in paged_rows(
        _CALL_COUNTS_QUERY,
        team,
        telemetry_team,
        window_start,
        window_end,
        "DataCatalogUsageTopicCallCounts",
        placeholders=_placeholders(piece_ids),
    ):
        counts[session][tool] += calls
    return counts


def _stored_json(value: object) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value) if value else None
    except json.JSONDecodeError:
        return value


def fetch_cohorts(team: Team, cohort_ids: Sequence[int]) -> list[CohortDefinition]:
    """The team's cohorts among `cohort_ids`. A missing id is left out, so the cohort counts as unknown."""
    cohorts = []
    for start in range(0, len(cohort_ids), _COHORT_BATCH):
        batch = cohort_ids[start : start + _COHORT_BATCH]
        with tags_context(product=Product.DATA_CATALOG, feature=Feature.ENRICHMENT, team_id=team.id):
            response = execute_hogql_query(
                query=parse_select(_COHORTS_QUERY),
                team=team,
                placeholders={
                    "ids": ast.Tuple(exprs=[ast.Constant(value=cohort_id) for cohort_id in batch]),
                    "row_limit": ast.Constant(value=len(batch)),
                },
                query_type="DataCatalogUsageTopicCohorts",
                workload=Workload.OFFLINE,
            )
        for cohort_id, is_static, filters, query in response.results or []:
            stored_query = _stored_json(query)
            cohorts.append(
                CohortDefinition(
                    id=int(cohort_id),
                    is_static=bool(is_static),
                    filters=_stored_json(filters),
                    query=stored_query or None,
                )
            )
    return cohorts


def _cohort_definitions(team: Team, bodies: Sequence[object]) -> dict[int, CohortDefinition]:
    """The cohorts that the bodies use, and the cohorts that those cohorts use, as deep as the scan follows."""
    found: dict[int, CohortDefinition] = {}
    wanted = {cohort_id for body in bodies for node in _dicts(body) for cohort_id in _cohort_ids(node) or []}
    for _ in range(_COHORT_DEPTH):
        wanted -= found.keys()
        if not wanted:
            break
        loaded = fetch_cohorts(team, sorted(wanted))
        found.update((cohort.id, cohort) for cohort in loaded)
        wanted = {
            cohort_id for cohort in loaded for node in _dicts(cohort.filters) for cohort_id in _cohort_ids(node) or []
        }
    return found


def cohort_changes(cohorts: Mapping[int, CohortDefinition], changed: Mapping[int, datetime]) -> dict[int, datetime]:
    """The last change of each cohort or of a cohort that it uses, because a query runs them all."""
    latest: dict[int, datetime | None] = {}

    def last_change(cohort_id: int, path: tuple[int, ...]) -> datetime | None:
        if cohort_id in latest:
            return latest[cohort_id]
        times = [changed.get(cohort_id)]
        cohort = cohorts.get(cohort_id)
        if cohort is not None and cohort_id not in path:
            nested = {other for node in _dicts(cohort.filters) for other in _cohort_ids(node) or []}
            times.extend(last_change(other, (*path, cohort_id)) for other in nested)
        found = max((time for time in times if time is not None), default=None)
        latest[cohort_id] = found
        return found

    return {cohort_id: time for cohort_id in cohorts if (time := last_change(cohort_id, ())) is not None}


def _last_changes(
    team: Team, scope: str, since: datetime, item_ids: Collection[str] | None = None
) -> dict[str, datetime]:
    entries = ActivityLog.objects.filter(
        team_id=team.id, scope=scope, activity__in=_CHANGE_ACTIVITIES, created_at__gte=since
    )
    if item_ids is not None:
        entries = entries.filter(item_id__in=list(item_ids))
    return {
        str(item_id): latest
        for item_id, latest in entries.order_by()
        .values("item_id")
        .annotate(latest=Max("created_at"))
        .values_list("item_id", "latest")
    }


def _test_account_filters_changed_at(team: Team, since: datetime) -> datetime | None:
    return ActivityLog.objects.filter(
        team_id=team.id,
        scope="Team",
        item_id=str(team.id),
        created_at__gte=since,
        detail__contains={"changes": [{"field": "test_account_filters"}]},
    ).aggregate(latest=Max("created_at"))["latest"]


def _load_saved_filters(team: Team, bodies: Sequence[object], since: datetime) -> SavedFilters:
    test_account_filters = list(team.test_account_filters or [])
    definitions = _cohort_definitions(team, [*bodies, test_account_filters])
    cohorts = cohort_reads(definitions)
    changed = _last_changes(team, "Cohort", since, [str(cohort_id) for cohort_id in definitions])
    changes = cohort_changes(definitions, {int(cohort_id): time for cohort_id, time in changed.items()})
    test_account_tables = query_tables(
        {"properties": test_account_filters}, SavedFilters(cohorts=cohorts, test_account_tables=frozenset())
    )
    test_cohorts = {cohort_id for node in _dicts(test_account_filters) for cohort_id in _cohort_ids(node) or []}
    times = [_test_account_filters_changed_at(team, since), *(changes.get(cohort_id) for cohort_id in test_cohorts)]
    return SavedFilters(
        cohorts=cohorts,
        test_account_tables=test_account_tables,
        cohort_changes=changes,
        test_accounts_changed_at=max((time for time in times if time is not None), default=None),
    )


def saved_field_tables(
    joins: Mapping[str, Collection[str]], expressions: Mapping[str, Collection[tuple[str, str]]]
) -> dict[str, frozenset[str] | None]:
    """The tables that each join and saved expression field reads, or None when the scan cannot tell.

    HogQL expands an expression in place, so an expression reads the tables of its own body, and of the join and
    expression fields that the body uses. An expression that does not parse, or a cycle of expressions, counts as
    unknown."""
    resolved: dict[str, frozenset[str] | None] = {}

    def reads(field: str, path: tuple[str, ...]) -> frozenset[str] | None:
        if field in resolved:
            return resolved[field]
        if field in path:
            return None
        found = set(joins.get(field, ()))
        for table_name, expression in expressions.get(field, ()):
            named = sql_tables(f"SELECT {expression} FROM {table_name}")
            if named is None:
                return None
            found |= named
            # The field's own name in its body is a part of a field chain, such as `plan` in `stripe.plan`.
            for other in set(_IDENTIFIER.findall(expression)) & (joins.keys() | expressions.keys()) - {field}:
                nested = reads(other, (*path, field))
                if nested is None:
                    return None
                found |= nested
        result = frozenset(found)
        resolved[field] = result
        return result

    return {field: reads(field, ()) for field in joins.keys() | expressions.keys()}


def _load_saved_fields(team: Team) -> dict[str, frozenset[str] | None]:
    # A soft-deleted join or expression can still have run before the scan, and an extra table only hides more.
    joins: dict[str, set[str]] = defaultdict(set)
    for field_name, joining_table in DataWarehouseJoin.objects.filter(team_id=team.id).values_list(
        "field_name", "joining_table_name"
    ):
        if field_name and joining_table:
            joins[field_name].add(joining_table)
    expressions: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for table_name, field_name, expression in DataWarehouseExpression.objects.for_team(team.id).values_list(
        "table_name", "field_name", "expression"
    ):
        if field_name:
            expressions[field_name].add((table_name, expression))
    return saved_field_tables(joins, expressions)


def load_read_sources(team: Team, calls: Sequence[ReadCall], since: datetime) -> ReadSources:
    """The saved definitions and filters that the calls ran, with the times they changed after ``since``."""
    names = {name for call in calls if call.tool == RUN_TOOL and (name := _payload_field(call, "name"))}
    short_ids = {
        short_id for call in calls if call.tool == INSIGHT_TOOL and (short_id := _payload_field(call, "insightId"))
    }
    # A deleted metric's name can belong to a new metric, so only live metrics count. A metric that someone
    # created or edited after the run fails the time check in `ReadSources.as_of`.
    metrics = (
        metrics_for_team(team).filter(name__in=names).values_list("name", "definition", "updated_at", "created_at")
        if names
        else []
    )
    definitions = {
        name: SavedDefinition(body=definition, changed_at=updated_at or created_at)
        for name, definition, updated_at, created_at in metrics
    }
    # An insight that someone deleted after the run still says what the run read. The insight API stamps
    # `last_modified_at` on every change to the query.
    rows = (
        Insight.objects_including_soft_deleted.filter(team_id=team.id, short_id__in=short_ids).values_list(
            "short_id", "query", "last_modified_at"
        )
        if short_ids
        else []
    )
    queries = {
        short_id: SavedDefinition(body=query, changed_at=changed_at)
        for short_id, query, changed_at in rows
        if isinstance(query, dict)
    }
    bodies = [
        *(call.payload for call in calls),
        *(saved.body for saved in definitions.values()),
        *(saved.body for saved in queries.values()),
    ]
    field_changes = [
        *_last_changes(team, "DataWarehouseJoin", since).values(),
        *_last_changes(team, "DataWarehouseExpression", since).values(),
    ]
    return ReadSources(
        metric_definitions=definitions,
        insight_queries=queries,
        saved_filters=_load_saved_filters(team, bodies, since),
        field_tables=_load_saved_fields(team),
        fields_changed_at=max(field_changes, default=None),
    )


def trace_session_tables(
    *,
    team: Team,
    telemetry_team: Team,
    window_start: datetime,
    window_end: datetime,
    sessions: Sequence[SessionText],
    members: Mapping[str, tuple[str, ...]],
) -> dict[str, frozenset[str] | None]:
    """The tables that each session read, keyed by session id. A joined conversation reads what its pieces read."""
    pieces_of = {session.session_id: members.get(session.session_id, (session.session_id,)) for session in sessions}
    piece_ids = [piece for pieces in pieces_of.values() for piece in pieces]
    batches = [piece_ids[start : start + _PIECE_BATCH] for start in range(0, len(piece_ids), _PIECE_BATCH)]
    calls: list[ReadCall] = []
    counts_by_piece: dict[str, Counter[str]] = {}
    for batch in batches:
        calls.extend(
            _fetch_calls(
                team=team,
                telemetry_team=telemetry_team,
                window_start=window_start,
                window_end=window_end,
                piece_ids=batch,
            )
        )
        counts_by_piece.update(
            _fetch_call_counts(
                team=team,
                telemetry_team=telemetry_team,
                window_start=window_start,
                window_end=window_end,
                piece_ids=batch,
            )
        )
    sources = load_read_sources(team, calls, window_start)
    calls_by_piece: dict[str, list[ReadCall]] = defaultdict(list)
    for call in calls:
        calls_by_piece[call.session].append(call)
    return {
        session.session_id: session_tables(
            (call for piece in pieces_of[session.session_id] for call in calls_by_piece.get(piece, ())),
            session.tools,
            sources,
            sum((counts_by_piece.get(piece, Counter()) for piece in pieces_of[session.session_id]), Counter()),
        )
        for session in sessions
    }
