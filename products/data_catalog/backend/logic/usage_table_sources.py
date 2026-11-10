"""Count the tables and views that agents found through their descriptions and then queried.

A metadata search that reads descriptions names the tables it returned. A table counts for a session
when a later query in that session reads it. PostHog's own tables stay out, so the list holds
connected sources and views. The count covers every session in the window, so it compares with
metric runs, and it needs no model call.
"""

import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping
from datetime import datetime
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.database.database import Database

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.sync import database_sync_to_async

from ..facade.contracts import TableSource
from .agent_sessions import stored_conversations
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
# This also reads `ts` in `extract(day from ts)` as a table. A table counts only when a search also returned
# it, so a column name rarely matches.
_READ_TABLE = re.compile(r"(?:from|join)\s+([`\"\w.\-]+)", re.IGNORECASE)
# A search prints a missing description as one of these.
_EMPTY_DESCRIPTIONS = frozenset({"", "null", "none"})
# Bounds the session list in one query, so the query text stays well under the size limit.
_SESSION_BATCH = 1000

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
LIMIT {row_limit}
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
    AND toString(a.properties.$session_id) IN {sessions}
    AND a.trace_id IN (
        SELECT properties.$ai_trace_id FROM events
        WHERE event = '$ai_generation'
            AND properties.$ai_span_name = 'execute-sql'
            AND timestamp >= {start}
            AND timestamp < {end}
            AND toString(properties.$mcp_project_uuid) = {project}
            AND toString(properties.$session_id) IN {sessions}
    )
LIMIT {row_limit}
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
    """The tables a search returned with a filled description.

    A column search can return only columns, so its filter names the table.
    """
    lines = [line for line in result.split("\n") if "|" in line and not line.startswith(("[", "- "))]
    if len(lines) < 2:
        return frozenset()
    header = [column.strip().lower() for column in lines[0].split("|")]
    rows = [line.split("|") for line in lines[1:]]
    if "description" in header:
        described = header.index("description")
        rows = [
            row for row in rows if len(row) > described and row[described].strip().lower() not in _EMPTY_DESCRIPTIONS
        ]
    names: set[str] = set()
    column = next((header.index(name) for name in _NAME_COLUMNS if name in header), None)
    if column is not None:
        names.update(row[column].strip() for row in rows if len(row) > column)
    if "table_name" not in header and rows:
        for match in _FILTERED_TABLE.finditer(query):
            names.update(re.findall(r"'([^']+)'", match.group(1)))
    return frozenset(name for name in names if _TABLE_NAME.fullmatch(name))


def _name_parts(name: str) -> list[str]:
    return [part for part in name.replace("`", "").replace('"', "").lower().split(".") if part]


def reads_table(sql: str, table: str) -> bool:
    """A query reads the table when the parts it names match the end of the table's qualified name.

    A query can leave out leading qualifiers, but a qualifier it names must match, so two tables with the
    same last name part stay apart.
    """
    return _names_read_table(_names_read(sql), _name_parts(table))


def _names_read(sql: str) -> list[list[str]]:
    return [_name_parts(match.group(1)) for match in _READ_TABLE.finditer(sql)]


def _names_read_table(names_read: Iterable[list[str]], table_parts: list[str]) -> bool:
    for read_parts in names_read:
        shared = min(len(read_parts), len(table_parts))
        if shared and read_parts[-shared:] == table_parts[-shared:]:
            return True
    return False


def build_table_sources(
    searches: Iterable[TableSearch], queries: Iterable[SessionQuery], native_tables: Collection[str] = ()
) -> list[TableSource]:
    """Rank tables by people, then sessions. PostHog's own tables stay out, because a team does not curate them."""
    tally = _TableTally(native_tables)
    tally.add(searches, queries)
    return tally.ranked()


class _TableTally:
    """Sessions and people per table. Each batch adds to it, so the SQL of one batch never outlives the batch."""

    def __init__(self, native_tables: Collection[str]) -> None:
        self._native_tables = native_tables
        self._sessions: dict[str, set[str]] = defaultdict(set)
        self._people: dict[str, set[str]] = defaultdict(set)

    def add(self, searches: Iterable[TableSearch], queries: Iterable[SessionQuery]) -> None:
        # Each query's table names are read once, because a session can search many times for many tables.
        reads_by_session: dict[str, list[tuple[datetime, list[list[str]]]]] = defaultdict(list)
        for query in queries:
            reads_by_session[query.session_id].append((query.occurred_at, _names_read(query.sql)))
        for search in searches:
            later = [names for at, names in reads_by_session[search.session_id] if at > search.occurred_at]
            for table in search.tables:
                if table in self._native_tables or table.startswith(_NATIVE_PREFIXES):
                    continue
                table_parts = _name_parts(table)
                if any(_names_read_table(names, table_parts) for names in later):
                    self._sessions[table].add(search.session_id)
                    self._people[table].add(search.person)

    def ranked(self) -> list[TableSource]:
        sources = [
            TableSource(name=table, sessions=len(sessions), people=len(self._people[table]))
            for table, sessions in self._sessions.items()
        ]
        sources.sort(key=lambda source: (-source.people, -source.sessions, source.name))
        return sources[:MAX_TABLE_SOURCES]


def _conversation_batches(conversations: Iterable[str], pieces_of: Mapping[str, set[str]]) -> Iterator[list[str]]:
    """Conversations in batches of about one session batch of pieces. A conversation never splits across batches."""
    batch: list[str] = []
    size = 0
    for conversation in conversations:
        count = len(pieces_of.get(conversation) or {conversation})
        if batch and size + count > _SESSION_BATCH:
            yield batch
            batch, size = [], 0
        batch.append(conversation)
        size += count
    if batch:
        yield batch


def fetch_table_sources(
    *,
    team: Team,
    telemetry_team: Team,
    window_start: datetime,
    window_end: datetime,
    units: Mapping[str, str] | None = None,
) -> list[TableSource]:
    """``units`` maps a session id to its conversation, so a search and a query in two pieces of one
    conversation still pair up."""
    units = units or {}
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
            searches.append(
                TableSearch(
                    session_id=units.get(session, session), person=person, occurred_at=occurred_at, tables=tables
                )
            )
    if not searches:
        return []
    database = Database.create_for(team=team)
    tally = _TableTally({*database.get_posthog_table_names(include_hidden=True), *database.get_system_table_names()})
    searches_by_conversation: dict[str, list[TableSearch]] = defaultdict(list)
    for search in searches:
        searches_by_conversation[search.session_id].append(search)
    pieces_of: dict[str, set[str]] = defaultdict(set)
    for piece, unit in units.items():
        pieces_of[unit].add(piece)
    # Most queries belong to sessions that searched nothing. The query reads only the searching sessions,
    # so those queries cannot use up the row limit.
    for conversations in _conversation_batches(sorted(searches_by_conversation), pieces_of):
        pieces = sorted(
            {piece for conversation in conversations for piece in pieces_of.get(conversation) or {conversation}}
        )
        queries = [
            SessionQuery(session_id=units.get(session, session), occurred_at=occurred_at, sql=sql)
            for session, occurred_at, sql in paged_rows(
                _QUERIES_QUERY,
                team,
                telemetry_team,
                window_start,
                window_end,
                "DataCatalogUsageTableQueries",
                placeholders={
                    **excluded,
                    "max_sql_chars": ast.Constant(value=_MAX_SQL_CHARS),
                    "sessions": ast.Tuple(exprs=[ast.Constant(value=piece) for piece in pieces]),
                },
            )
            if sql
        ]
        tally.add(
            (search for conversation in conversations for search in searches_by_conversation[conversation]), queries
        )
    return tally.ranked()


def _collect(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> int:
    window = usage_snapshot_window(team_id, snapshot_id)
    sources = fetch_table_sources(
        team=Team.objects.get(id=team_id),
        telemetry_team=Team.objects.get(id=telemetry_team_id),
        window_start=window.start,
        window_end=window.end,
        units=stored_conversations(team_id, snapshot_id),
    )
    write_payload_sections(team_id, snapshot_id, table_sources=sources)
    return len(sources)


async def collect_table_sources_into_snapshot(*, team_id: int, snapshot_id: UUID, telemetry_team_id: int) -> int:
    return await database_sync_to_async(_collect, thread_sensitive=False)(
        team_id=team_id, snapshot_id=snapshot_id, telemetry_team_id=telemetry_team_id
    )
