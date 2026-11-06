"""Count the tables and views that agents found through their descriptions and then queried.

A metadata search that reads descriptions names the tables it returned. A table counts for a session
when a later query in that session reads it. PostHog's own tables stay out, so the list holds
connected sources and views. The count covers every session in the window, so it compares with
metric runs, and it needs no model call.
"""

import re
from collections import defaultdict
from collections.abc import Collection, Iterable
from datetime import datetime
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.database.database import Database

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.sync import database_sync_to_async

from ..facade.contracts import TableSource
from .usage_adjusted import paged_rows
from .usage_snapshots import usage_snapshot_window, write_payload_sections
from .usage_topics import query_text, result_text

MAX_TABLE_SOURCES = 25
_MAX_INPUT_CHARS = 2000
_MAX_OUTPUT_CHARS = 6000
_MAX_SQL_CHARS = 4000
_EXCLUDED_SOURCES = ("self_driving", "wizard")
_TABLE_NAME = re.compile(r"[\w.\-]+")
_NAME_COLUMNS = ("table_name", "name", "table")
_NATIVE_PREFIXES = ("system.", "posthog.")
_FILTERED_TABLE = re.compile(r"table_name\s*(?:=|in\s*\()\s*([^)\n]*)", re.IGNORECASE)

# `ai_events` is ordered by trace, so trace ids come from `events`, which is ordered by time.
_SEARCHES_QUERY = """
SELECT
    toString(a.properties.$session_id) AS session,
    a.distinct_id,
    a.timestamp,
    substring(ifNull(a.input_state, ''), 1, {max_input_chars}) AS input,
    substring(ifNull(a.output_state, ''), 1, {max_output_chars}) AS output
FROM posthog.ai_events AS a
WHERE a.event = '$ai_span'
    AND a.span_name = 'execute-sql'
    AND a.is_error = 0
    AND a.timestamp >= {start}
    AND a.timestamp < {end}
    AND toString(a.properties.$mcp_project_uuid) = {project}
    AND toString(a.properties.source) NOT IN {excluded_sources}
    AND length(toString(a.properties.$session_id)) > 0
    AND positionCaseInsensitive(ifNull(a.input_state, ''), 'information_schema') > 0
    AND positionCaseInsensitive(ifNull(a.input_state, ''), 'description') > 0
    AND a.trace_id IN (
        SELECT properties.$ai_trace_id FROM events
        WHERE event = '$ai_span'
            AND properties.$ai_span_name = 'execute-sql'
            AND timestamp >= {start}
            AND timestamp < {end}
            AND toString(properties.$mcp_project_uuid) = {project}
    )
LIMIT 50000
"""

_QUERIES_QUERY = """
SELECT
    toString(a.properties.$session_id) AS session,
    a.timestamp,
    substring(JSONExtractString(ifNull(a.output_choices, ''), 1, 'content'), 1, {max_sql_chars}) AS sql
FROM posthog.ai_events AS a
WHERE a.event = '$ai_generation'
    AND a.span_name = 'execute-sql'
    AND a.is_error = 0
    AND a.timestamp >= {start}
    AND a.timestamp < {end}
    AND toString(a.properties.$mcp_project_uuid) = {project}
    AND toString(a.properties.source) NOT IN {excluded_sources}
    AND a.trace_id IN (
        SELECT properties.$ai_trace_id FROM events
        WHERE event = '$ai_generation'
            AND properties.$ai_span_name = 'execute-sql'
            AND timestamp >= {start}
            AND timestamp < {end}
            AND toString(properties.$mcp_project_uuid) = {project}
    )
LIMIT 50000
"""


@frozen
class TableSearch:
    session_id: str
    person: str
    occurred_at: datetime
    tables: frozenset[str]


@frozen
class SessionQuery:
    session_id: str
    occurred_at: datetime
    sql: str


def tables_in_search(query: str, result: str) -> frozenset[str]:
    """The tables a search returned. A column search can return only columns, so its filter names the table."""
    lines = [line for line in result.split("\n") if "|" in line and not line.startswith(("[", "- "))]
    if len(lines) < 2:
        return frozenset()
    header = [column.strip().lower() for column in lines[0].split("|")]
    names: set[str] = set()
    column = next((header.index(name) for name in _NAME_COLUMNS if name in header), None)
    if column is not None:
        names.update(line.split("|")[column].strip() for line in lines[1:] if len(line.split("|")) > column)
    if "table_name" not in header:
        for match in _FILTERED_TABLE.finditer(query):
            names.update(re.findall(r"'([^']+)'", match.group(1)))
    return frozenset(name for name in names if _TABLE_NAME.fullmatch(name))


def reads_table(sql: str, table: str) -> bool:
    last_part = re.escape(table.split(".")[-1])
    return re.search(rf"(?:from|join)\s+[`\"]?(?:[\w.\-]+\.)?{last_part}\b", sql, re.IGNORECASE) is not None


def build_table_sources(
    searches: Iterable[TableSearch], queries: Iterable[SessionQuery], native_tables: Collection[str] = ()
) -> list[TableSource]:
    """Rank tables by people, then sessions. PostHog's own tables stay out, because a team does not curate them."""
    queries_by_session: dict[str, list[SessionQuery]] = defaultdict(list)
    for query in queries:
        queries_by_session[query.session_id].append(query)
    sessions: dict[str, set[str]] = defaultdict(set)
    people: dict[str, set[str]] = defaultdict(set)
    for search in searches:
        later = [query for query in queries_by_session[search.session_id] if query.occurred_at > search.occurred_at]
        for table in search.tables:
            if table in native_tables or table.startswith(_NATIVE_PREFIXES):
                continue
            if any(reads_table(query.sql, table) for query in later):
                sessions[table].add(search.session_id)
                people[table].add(search.person)
    sources = [TableSource(name=table, sessions=len(sessions[table]), people=len(people[table])) for table in sessions]
    sources.sort(key=lambda source: (-source.people, -source.sessions, source.name))
    return sources[:MAX_TABLE_SOURCES]


def fetch_table_sources(
    *, team: Team, telemetry_team: Team, window_start: datetime, window_end: datetime
) -> list[TableSource]:
    excluded = {"excluded_sources": ast.Tuple(exprs=[ast.Constant(value=source) for source in _EXCLUDED_SOURCES])}
    searches = []
    for session, person, occurred_at, raw_input, raw_output in paged_rows(
        _SEARCHES_QUERY,
        team,
        telemetry_team,
        window_start,
        window_end,
        "DataCatalogUsageTableSearches",
        placeholders={
            **excluded,
            "max_input_chars": ast.Constant(value=_MAX_INPUT_CHARS),
            "max_output_chars": ast.Constant(value=_MAX_OUTPUT_CHARS),
        },
    ):
        tables = tables_in_search(query_text(raw_input), result_text(raw_output))
        if tables:
            searches.append(TableSearch(session_id=session, person=person, occurred_at=occurred_at, tables=tables))
    if not searches:
        return []
    # Most queries belong to sessions that searched nothing, so only the searching sessions stay in memory.
    searching = {search.session_id for search in searches}
    queries = [
        SessionQuery(session_id=session, occurred_at=occurred_at, sql=sql)
        for session, occurred_at, sql in paged_rows(
            _QUERIES_QUERY,
            team,
            telemetry_team,
            window_start,
            window_end,
            "DataCatalogUsageTableQueries",
            placeholders={**excluded, "max_sql_chars": ast.Constant(value=_MAX_SQL_CHARS)},
        )
        if session in searching and sql
    ]
    database = Database.create_for(team=team)
    native = {*database.get_posthog_table_names(include_hidden=True), *database.get_system_table_names()}
    return build_table_sources(searches, queries, native)


def _collect(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> int:
    window = usage_snapshot_window(team_id, snapshot_id)
    sources = fetch_table_sources(
        team=Team.objects.get(id=team_id),
        telemetry_team=Team.objects.get(id=telemetry_team_id),
        window_start=window.start,
        window_end=window.end,
    )
    write_payload_sections(team_id, snapshot_id, table_sources=sources)
    return len(sources)


async def collect_table_sources_into_snapshot(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> int:
    return await database_sync_to_async(_collect, thread_sensitive=False)(
        team_id=team_id, snapshot_id=snapshot_id, telemetry_team_id=telemetry_team_id
    )
