from datetime import datetime, timedelta

from django.db import models

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.log_entries import LOG_ENTRIES_TTL_DAYS
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User

# Console log timestamps come from the client clock, so allow some slack around the recording's own bounds.
CONSOLE_LOG_WINDOW_SLACK = timedelta(seconds=100)
# Ingestion caps each console argument at 2999 characters, but a call with many arguments joins them all.
MAX_CONSOLE_MESSAGE_LENGTH = 3000
MAX_CONSOLE_LOGS_PAGE_SIZE = 500


class ConsoleLogLevel(models.TextChoices):
    INFO = "info", "Info"
    WARN = "warn", "Warn"
    ERROR = "error", "Error"


@frozen
class ConsoleLogEntry:
    timestamp: datetime
    level: str
    message: str
    truncated: bool


@frozen
class ConsoleLogsPage:
    results: list[ConsoleLogEntry]
    has_more: bool
    logs_expired: bool


def console_logs_expired(recording_start: datetime, now: datetime) -> bool:
    return recording_start < now - timedelta(days=LOG_ENTRIES_TTL_DAYS)


def get_console_logs(
    *,
    team: Team,
    user: User | None,
    session_id: str,
    recording_start: datetime,
    recording_end: datetime,
    now: datetime,
    level: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ConsoleLogsPage:
    date_from = recording_start - CONSOLE_LOG_WINDOW_SLACK
    date_to = recording_end + CONSOLE_LOG_WINDOW_SLACK
    if after is not None:
        date_from = max(date_from, after)
    if before is not None:
        date_to = min(date_to, before)

    expired = console_logs_expired(recording_start, now)
    if date_from > date_to:
        return ConsoleLogsPage(results=[], has_more=False, logs_expired=expired)

    level_filter: ast.Expr = ast.Constant(value=True)
    if level is not None:
        level_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["level"]),
            right=ast.Constant(value=level),
        )

    query = parse_select(
        """
        SELECT
            timestamp,
            level,
            left(message, {max_message_length}),
            lengthUTF8(message) > {max_message_length}
        FROM console_logs_log_entries
        WHERE log_source_id = {session_id}
            AND timestamp >= {date_from}
            AND timestamp <= {date_to}
            AND {level_filter}
        ORDER BY timestamp ASC, level ASC, message ASC
        LIMIT {limit}
        OFFSET {offset}
        """,
        placeholders={
            "session_id": ast.Constant(value=session_id),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "level_filter": level_filter,
            "max_message_length": ast.Constant(value=MAX_CONSOLE_MESSAGE_LENGTH),
            # One extra row tells us whether another page exists.
            "limit": ast.Constant(value=limit + 1),
            "offset": ast.Constant(value=offset),
        },
    )

    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
    response = execute_hogql_query(
        query=query,
        team=team,
        user=user,
        query_type="SessionRecordingConsoleLogs",
        workload=Workload.ONLINE,
    )

    rows = response.results or []
    entries = [
        ConsoleLogEntry(timestamp=timestamp, level=row_level, message=message, truncated=bool(truncated))
        for timestamp, row_level, message, truncated in rows[:limit]
    ]
    return ConsoleLogsPage(results=entries, has_more=len(rows) > limit, logs_expired=expired)
