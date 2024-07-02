import enum
import dataclasses
import datetime as dt
from typing import Any
import typing
from posthog.client import sync_execute


class LogEntryLevel(enum.StrEnum):
    """Enumeration of batch export log levels."""

    DEBUG = "DEBUG"
    LOG = "LOG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclasses.dataclass(frozen=True)
class LogEntry:
    """Represents a single batch export log entry."""

    team_id: int
    log_source_id: str
    run_id: str
    timestamp: dt.datetime
    level: LogEntryLevel
    message: str


def process_log_entries_query_params(
    team_id: int,
    log_source_id: str,
    run_id: str | None = None,
    after: dt.datetime | None = None,
    before: dt.datetime | None = None,
    search: str | None = None,
    level_filter: typing.Optional[list[LogEntryLevel]] = None,
) -> tuple[list[str], dict[str, Any]]:
    if level_filter is None:
        level_filter = []
    clickhouse_where_parts: list[str] = []
    clickhouse_kwargs: dict[str, Any] = {}

    clickhouse_where_parts.append("log_source_id = %(log_source_id)s")
    clickhouse_kwargs["log_source_id"] = log_source_id
    clickhouse_where_parts.append("team_id = %(team_id)s")
    clickhouse_kwargs["team_id"] = team_id

    if run_id is not None:
        clickhouse_where_parts.append("instance_id = %(instance_id)s")
        clickhouse_kwargs["instance_id"] = run_id
    if after is not None:
        clickhouse_where_parts.append("timestamp > toDateTime64(%(after)s, 6)")
        clickhouse_kwargs["after"] = after.isoformat().replace("+00:00", "")
    if before is not None:
        clickhouse_where_parts.append("timestamp < toDateTime64(%(before)s, 6)")
        clickhouse_kwargs["before"] = before.isoformat().replace("+00:00", "")
    if search:
        clickhouse_where_parts.append("message ILIKE %(search)s")
        clickhouse_kwargs["search"] = f"%{search}%"
    if len(level_filter) > 0:
        clickhouse_where_parts.append("upper(level) in %(levels)s")
        clickhouse_kwargs["levels"] = level_filter

    return clickhouse_where_parts, clickhouse_kwargs


def fetch_log_entries(
    *,
    log_source_id: str,
    team_id: int,
    run_id: str | None = None,
    after: dt.datetime | None = None,
    before: dt.datetime | None = None,
    search: str | None = None,
    limit: int | None = None,
    level_filter: typing.Optional[list[LogEntryLevel]] = None,
) -> list[LogEntry]:
    """Fetch a list of batch export log entries from ClickHouse."""
    if level_filter is None:
        level_filter = []
    clickhouse_where_parts: list[str] = []
    clickhouse_kwargs: dict[str, typing.Any] = {}

    clickhouse_where_parts, clickhouse_kwargs = process_log_entries_query_params(
        team_id=team_id,
        log_source_id=log_source_id,
        run_id=run_id,
        after=after,
        before=before,
        search=search,
        level_filter=level_filter,
    )

    clickhouse_query = f"""
        SELECT team_id, log_source_id AS log_source_id, instance_id AS run_id, timestamp, upper(level) as level, message FROM log_entries
        WHERE {' AND '.join(clickhouse_where_parts)} ORDER BY timestamp DESC {f'LIMIT {limit}' if limit else ''}
    """

    return [LogEntry(*result) for result in typing.cast(list, sync_execute(clickhouse_query, clickhouse_kwargs))]
