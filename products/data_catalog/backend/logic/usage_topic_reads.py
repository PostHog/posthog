"""Trace the tables and views that the sessions of each topic read.

A topic title sums up the questions of its sessions. A reader who may not read a table that one of those
sessions read must not see the title, so the scan stores the tables of each topic, and a read hides only the
topics that name a table the reader is denied. When the scan cannot trace what a session read, the tables of
its topic are unknown, and a reader with any denied table does not see that topic.
"""

import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from datetime import datetime
from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models import Team

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
class ReadSources:
    """The saved definitions that calls read by reference: metrics by name, insights by short id."""

    metric_definitions: Mapping[str, SavedDefinition]
    insight_queries: Mapping[str, SavedDefinition]

    def as_of(self, at: datetime) -> "ReadSources":
        """Only a definition that did not change after a call still says what that call read."""
        return ReadSources(
            metric_definitions=_unchanged(self.metric_definitions, at),
            insight_queries=_unchanged(self.insight_queries, at),
        )


def _unchanged[K](saved: Mapping[K, SavedDefinition], at: datetime) -> dict[K, SavedDefinition]:
    return {key: item for key, item in saved.items() if item.changed_at is not None and item.changed_at <= at}


def sql_tables(sql: str) -> frozenset[str] | None:
    """The tables a HogQL query names, or None when it does not parse."""
    try:
        return frozenset(table_names_as_written({"query": sql}, keep_table_functions=True))
    except ValidationError:
        return None


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
    for key in ("type", "breakdown_type"):
        marker = str(node.get(key) or "")
        if marker == "hogql" or marker.startswith("data_warehouse"):
            return True
    return any(_EXPRESSION.search(key) and value for key, value in node.items())


def _refers_to_action(node: dict[str, Any]) -> bool:
    return node.get("kind") == "ActionsNode" or node.get("type") == "actions" or "actionId" in node


def query_tables(query: object) -> frozenset[str] | None:
    """The tables that a query object reads past PostHog's own tables, or None when the scan cannot tell.

    A HogQL query names its tables, and a warehouse node names its table. A query runs the stored steps of an
    action that it refers to, and their filters can read any table, so the scan cannot tell. Every other node
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
    return frozenset(tables)


def metric_tables(definition: dict[str, Any] | None) -> frozenset[str] | None:
    """A stub runs no query, and a markdown metric only returns steps that the agent then runs as queries."""
    if definition is None or definition.get("kind") == MARKDOWN_DEFINITION_KIND:
        return frozenset()
    return query_tables(definition)


def insight_tables(saved: SavedDefinition | None, filters_override: object) -> frozenset[str] | None:
    """An insight run merges its filter override into the saved query, so the override's filters count too.

    A variable override only sets values, so it reads no table."""
    if saved is None:
        return None
    query = query_tables(saved.body)
    override = frozenset() if filters_override is None else query_tables(filters_override)
    return None if query is None or override is None else query | override


def _payload_field(call: ReadCall, field: str) -> str:
    value = call.payload.get(field) if isinstance(call.payload, dict) else None
    return str(value) if value else ""


def call_tables(call: ReadCall, sources: ReadSources) -> frozenset[str] | None:
    """The tables that one call read, or None when the scan cannot tell."""
    if call.cut:
        return None
    if call.tool == SQL_TOOL:
        # A metadata search logs as a span with its query in the input, and every other query as a generation.
        sql = call.sql if call.event == "$ai_generation" else _payload_field(call, "query")
        return sql_tables(sql) if sql else None
    current = sources.as_of(call.at)
    if call.tool == RUN_TOOL:
        metric = current.metric_definitions.get(_payload_field(call, "name"))
        return metric_tables(metric.body) if metric is not None else None
    if call.tool == INSIGHT_TOOL:
        overrides = call.payload.get("filters_override") if isinstance(call.payload, dict) else None
        insight = current.insight_queries.get(_payload_field(call, "insightId"))
        return insight_tables(insight, overrides)
    if call.tool.startswith(DATA_TOOL_PREFIX):
        return query_tables(call.payload)
    # A dashboard run reads the insights on the dashboard as it is now, which can differ from the run.
    return None


def session_tables(calls: Iterable[ReadCall], tools: Collection[str], sources: ReadSources) -> frozenset[str] | None:
    """The tables that one session read, or None when the scan cannot tell for one of its calls.

    Telemetry can lose a call, so a data tool that the session used with no call found also makes the answer
    unknown."""
    tables: set[str] = set()
    traced: set[str] = set()
    for call in calls:
        found = call_tables(call, sources)
        if found is None:
            return None
        tables |= found
        traced.add(call.tool)
    if any(is_data_tool(tool) and tool not in traced for tool in tools):
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
        placeholders={
            "tools": ast.Tuple(exprs=[ast.Constant(value=tool) for tool in DATA_TOOLS]),
            "tool_prefix": ast.Constant(value=DATA_TOOL_PREFIX),
            "sessions": ast.Tuple(exprs=[ast.Constant(value=piece) for piece in piece_ids]),
            "max_chars": ast.Constant(value=READ_CHARS),
        },
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


def _load_sources(team: Team, calls: Sequence[ReadCall]) -> ReadSources:
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
    return ReadSources(metric_definitions=definitions, insight_queries=queries)


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
    calls = [
        call
        for start in range(0, len(piece_ids), _PIECE_BATCH)
        for call in _fetch_calls(
            team=team,
            telemetry_team=telemetry_team,
            window_start=window_start,
            window_end=window_end,
            piece_ids=piece_ids[start : start + _PIECE_BATCH],
        )
    ]
    sources = _load_sources(team, calls)
    calls_by_piece: dict[str, list[ReadCall]] = defaultdict(list)
    for call in calls:
        calls_by_piece[call.session].append(call)
    return {
        session.session_id: session_tables(
            (call for piece in pieces_of[session.session_id] for call in calls_by_piece.get(piece, ())),
            session.tools,
            sources,
        )
        for session in sessions
    }
