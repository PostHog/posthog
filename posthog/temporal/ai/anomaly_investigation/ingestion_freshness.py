"""How complete the newest data is when the investigation starts.

An alert with no evaluation delay scores the newest bucket. When ingestion is behind, part of
that bucket's events have not arrived yet, so a count or a unique-user total reads low and fills
in later. The agent cannot see this from the alerted series alone, and `created_at` does not help,
because it records capture time and not insertion time. Lag shows only as missing events: the
newest timestamp is old, and per-minute volume falls step by step toward it.

The numbers are cheap, so they go into the agent's first message instead of costing it a tool call.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.models import Team

logger = structlog.get_logger(__name__)

FRESHNESS_WINDOW = timedelta(hours=3)
FRESHNESS_BUCKET = timedelta(minutes=5)
# Ingestion normally keeps the newest event within a minute or two of now. Past this age, the
# block states that ingestion is behind, so the agent does not have to infer it from the counts.
LAG_WARNING_AGE = timedelta(minutes=10)


@frozen
class FreshnessBucket:
    start: datetime
    events: int


def describe_ingestion_freshness(*, team: Team, event: str | None, evaluation_delay_intervals: int) -> str:
    """A plain-text block with the newest event's age and recent volume per 5 minutes.

    Measures ``event`` when the alerted series names one, otherwise every event. Never raises:
    this only enriches the agent's context, so a failed query must not fail an investigation
    that would otherwise have run.
    """
    try:
        measured_at, newest, buckets = _query_freshness(team=team, event=event)
    except Exception:
        logger.warning("anomaly_investigation.ingestion_freshness_failed", exc_info=True)
        return ""
    return render_ingestion_freshness(
        event=event,
        measured_at=measured_at,
        newest=newest,
        buckets=buckets,
        evaluation_delay_intervals=evaluation_delay_intervals,
    )


def render_ingestion_freshness(
    *,
    event: str | None,
    measured_at: datetime,
    newest: datetime | None,
    buckets: list[FreshnessBucket],
    evaluation_delay_intervals: int,
) -> str:
    subject = f'event "{event}"' if event else "all events"
    lines = [f"Ingestion freshness for {subject}, measured at {_format_time(measured_at)}:"]
    if newest is None:
        lines.append(f"- No events in the last {_format_duration(FRESHNESS_WINDOW)}.")
    else:
        age = max(measured_at - newest, timedelta(0))
        lines.append(
            f"- Newest event timestamp: {_format_time(newest)}, {_format_duration(age)} before the measurement."
        )
        if age >= LAG_WARNING_AGE:
            lines.append(
                f"- Ingestion is behind: no event with a timestamp in the last {_format_duration(age)} has arrived. "
                "Every bucket after the newest event is empty, and the buckets before it can still be filling."
            )
    if evaluation_delay_intervals:
        lines.append(f"- Alert evaluation delay: {evaluation_delay_intervals} interval(s).")
    else:
        lines.append(
            "- Alert evaluation delay: 0. The check scores the most recent bucket, which is still filling while ingestion is behind."
        )
    counts = _fill_gaps(measured_at=measured_at, buckets=buckets)
    if counts:
        lines.append(
            f"- Events per {_format_duration(FRESHNESS_BUCKET)}, oldest first: "
            + ", ".join(f"{start.strftime('%H:%M')} {events:,}" for start, events in counts)
            + "."
        )
    return "\n".join(lines)


def _query_freshness(*, team: Team, event: str | None) -> tuple[datetime, datetime | None, list[FreshnessBucket]]:
    event_filter = "event = {event} AND " if event else ""
    response = execute_hogql_query(
        query=(
            "SELECT toStartOfInterval(timestamp, toIntervalMinute({bucket_minutes})) AS bucket, "
            "count() AS events, max(timestamp) AS newest, now() AS measured_at "
            "FROM events "
            f"WHERE {event_filter}timestamp >= now() - toIntervalMinute({{window_minutes}}) AND timestamp <= now() "
            "GROUP BY bucket ORDER BY bucket"
        ),
        team=team,
        placeholders={
            "event": ast.Constant(value=event),
            "bucket_minutes": ast.Constant(value=int(FRESHNESS_BUCKET.total_seconds() // 60)),
            "window_minutes": ast.Constant(value=int(FRESHNESS_WINDOW.total_seconds() // 60)),
        },
    )
    rows = response.results or []
    if not rows:
        # Without a row the query returns no `now()` either, so the age is measured from this clock.
        return datetime.now(team.timezone_info), None, []
    buckets = [FreshnessBucket(start=row[0], events=int(row[1])) for row in rows]
    return rows[0][3], max(row[2] for row in rows), buckets


def _fill_gaps(*, measured_at: datetime, buckets: list[FreshnessBucket]) -> list[tuple[datetime, int]]:
    """Every bucket from the first returned one to the measurement, with zero where no event landed.

    The query returns only buckets that hold events, and the empty buckets at the end are the
    clearest sign of lag, so they have to be shown and not skipped.
    """
    if not buckets:
        return []
    by_start = {bucket.start: bucket.events for bucket in buckets}
    counts = []
    start = buckets[0].start
    while start <= measured_at:
        counts.append((start, by_start.get(start, 0)))
        start += FRESHNESS_BUCKET
    return counts


def _format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M %Z").strip()


def _format_duration(value: timedelta) -> str:
    minutes = int(value.total_seconds() // 60)
    if minutes < 1:
        return "under 1 minute"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
