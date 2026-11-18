from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import (
    Iterable,
    Iterator,
    Sequence,
    Set as AbstractSet,
)
from typing import IO, Any

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.temporal.health_checks.rollups.framework import DailyRollup
from posthog.utils import ensure_utc

logger = structlog.get_logger(__name__)

TEAM_ID_RANGE_COUNT = 16

SPOOL_MAX_BYTES = 64 * 1024 * 1024

FILL_QUERY_SETTINGS = {"max_execution_time": 1800, "max_threads": 8}


class DayOverRowCap(Exception):
    """The day has more rows than the rollup allows, so nothing of it may be published."""


@frozen
class TeamIdRange:
    start: int
    end: int


@frozen(frozen=False)
class DayFill:
    """One filled day, written in COPY text format into `buffer` and ready to publish.

    Close it once published, or once it is refused, to free the spooled file.
    """

    day: dt.date
    row_count: int
    event_count: int
    buffer: IO[bytes]

    def chunks(self, size: int = 1024 * 1024) -> Iterator[bytes]:
        self.buffer.seek(0)
        while chunk := self.buffer.read(size):
            yield chunk

    def close(self) -> None:
        self.buffer.close()


def team_id_ranges(team_ids: Iterable[int], count: int = TEAM_ID_RANGE_COUNT) -> list[TeamIdRange]:
    """Split the team ids into at most `count` ranges that hold about the same number of teams.

    Team ids are dense at the top, where active teams are, so equal-width ranges would put most
    teams in the last few ranges.
    """
    ids = sorted(set(team_ids))
    if not ids:
        return []
    count = max(1, min(count, len(ids)))
    starts = [ids[(len(ids) * index) // count] for index in range(count)]
    ends = [*starts[1:], ids[-1] + 1]
    return [TeamIdRange(start=start, end=end) for start, end in zip(starts, ends)]


def _copy_text(value: Any) -> str:
    """Format one value for the Postgres COPY text format."""
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, dt.datetime):
        return ensure_utc(value).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value)
    if "\x00" in text:
        raise ValueError("COPY text cannot hold a NUL byte")
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _row_columns(rollup: type[DailyRollup]) -> tuple[str, ...]:
    return (rollup.columns[0], *rollup.columns[2:])


@frozen
class _StringLimit:
    position: int
    max_length: int


def _string_limits(rollup: type[DailyRollup]) -> list[_StringLimit]:
    """The row position and max_length of every length-limited column."""
    limits = []
    for position, column in enumerate(_row_columns(rollup)):
        max_length = getattr(rollup.model._meta.get_field(column), "max_length", None)
        if max_length is not None:
            limits.append(_StringLimit(position=position, max_length=max_length))
    return limits


def _storable(row: Sequence[Any], string_limits: list[_StringLimit]) -> bool:
    for limit in string_limits:
        value = row[limit.position]
        if isinstance(value, str) and (len(value) > limit.max_length or "\x00" in value):
            return False
    return True


def _fetch_rows(rollup: type[DailyRollup], day: dt.date, team_ids: AbstractSet[int]) -> Iterator[Sequence[Any]]:
    params = {
        **rollup.fill_params(),
        "day_start": f"{day.isoformat()} 00:00:00",
        "day_end": f"{(day + dt.timedelta(days=1)).isoformat()} 00:00:00",
    }
    sql = rollup.fill_sql()
    # ClickHouse stops a range at the cap, so one oversized range cannot fill the worker's memory.
    settings = {
        **FILL_QUERY_SETTINGS,
        "max_result_rows": rollup.max_rows_per_day + 1,
        "result_overflow_mode": "break",
    }
    for team_range in team_id_ranges(team_ids):
        with tags_context(product=rollup.product, feature=Feature.HEALTH_CHECK, name=f"rollup_{rollup.table()}"):
            rows = sync_execute(
                sql,
                {**params, "team_id_start": team_range.start, "team_id_end": team_range.end},
                settings=settings,
                workload=Workload.OFFLINE,
            )
        if len(rows) > rollup.max_rows_per_day:
            raise DayOverRowCap(f"one team id range has more than {rollup.max_rows_per_day:,} rows")
        yield from rows


def fill_day(rollup: type[DailyRollup], day: dt.date, live_team_ids: AbstractSet[int]) -> DayFill:
    """Read one UTC day from ClickHouse, one team id range at a time, into a COPY buffer.

    Rows for teams that no longer exist and rows that do not fit the table are dropped here,
    before anything reaches Postgres. A day over the row cap raises DayOverRowCap.
    """
    event_count_position = _row_columns(rollup).index("event_count")
    string_limits = _string_limits(rollup)

    buffer: IO[bytes] = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES, mode="w+b")
    row_count = 0
    event_count = 0
    dropped_unknown_team = 0
    dropped_unstorable = 0
    try:
        for row in _fetch_rows(rollup, day, live_team_ids):
            if row[0] not in live_team_ids:
                dropped_unknown_team += 1
                continue
            if not _storable(row, string_limits):
                dropped_unstorable += 1
                continue
            values = (row[0], day, *row[1:])
            buffer.write(("\t".join(_copy_text(value) for value in values) + "\n").encode())
            row_count += 1
            event_count += int(row[event_count_position])
            if row_count > rollup.max_rows_per_day:
                raise DayOverRowCap(f"the day has more than {rollup.max_rows_per_day:,} rows")
    except BaseException:
        buffer.close()
        raise

    logger.info(
        "daily rollup filled",
        table=rollup.table(),
        day=day.isoformat(),
        rows=row_count,
        events=event_count,
        dropped_unknown_team=dropped_unknown_team,
        dropped_unstorable=dropped_unstorable,
    )
    return DayFill(day=day, row_count=row_count, event_count=event_count, buffer=buffer)
