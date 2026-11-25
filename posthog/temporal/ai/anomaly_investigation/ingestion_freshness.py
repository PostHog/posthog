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

from posthog.models import Team

logger = structlog.get_logger(__name__)

FRESHNESS_WINDOW_MINUTES = 180
FRESHNESS_BUCKET_MINUTES = 5
# Ingestion normally keeps the newest event within a minute or two of now. Past this age, the
# block states that ingestion is behind, so the agent does not have to infer it from the counts.
LAG_WARNING_AGE = timedelta(minutes=10)


def describe_ingestion_freshness(*, team: Team, event: str | None, evaluation_delay_intervals: int) -> str:
    """A plain-text block with the newest event's age and recent volume per 5 minutes.

    Measures ``event`` when the alerted series names one, otherwise every event. Never raises:
    this only enriches the agent's context, so a failed query must not fail an investigation
    that would otherwise have run.
    """
    try:
        measured_at, newest, counts = _query_freshness(team=team, event=event)
    except Exception:
        logger.warning("anomaly_investigation.ingestion_freshness_failed", exc_info=True)
        return ""
    return render_ingestion_freshness(
        event=event,
        measured_at=measured_at,
        newest=newest,
        counts=counts,
        evaluation_delay_intervals=evaluation_delay_intervals,
    )


def render_ingestion_freshness(
    *,
    event: str | None,
    measured_at: datetime,
    newest: datetime | None,
    counts: dict[datetime, int],
    evaluation_delay_intervals: int,
) -> str:
    """``counts`` holds only the buckets with events, keyed by bucket start."""
    subject = f'event "{event}"' if event else "all events"
    lines = [f"Ingestion freshness for {subject}, measured at {_format_time(measured_at)}:"]
    if newest is None:
        lines.append(f"- No events in the last {_format_minutes(FRESHNESS_WINDOW_MINUTES)}.")
    else:
        age_minutes = max(int((measured_at - newest).total_seconds() // 60), 0)
        lines.append(
            f"- Newest event timestamp: {_format_time(newest)}, {_format_minutes(age_minutes)} before the measurement."
        )
        if timedelta(minutes=age_minutes) >= LAG_WARNING_AGE:
            lines.append(
                f"- Ingestion is behind: no event with a timestamp in the last {_format_minutes(age_minutes)} has arrived. "
                "Every bucket after the newest event is empty, and the buckets before it can still be filling."
            )
    if evaluation_delay_intervals:
        lines.append(f"- Alert evaluation delay: {evaluation_delay_intervals} interval(s).")
    else:
        lines.append(
            "- Alert evaluation delay: 0. The check scores the most recent bucket, which is still filling while ingestion is behind."
        )
    if counts:
        lines.append(
            f"- Events per {_format_minutes(FRESHNESS_BUCKET_MINUTES)}, oldest first: "
            + ", ".join(f"{start.strftime('%H:%M')} {events:,}" for start, events in _fill_gaps(measured_at, counts))
            + "."
        )
    return "\n".join(lines)


def _query_freshness(*, team: Team, event: str | None) -> tuple[datetime, datetime | None, dict[datetime, int]]:
    query = (
        "SELECT toStartOfInterval(timestamp, toIntervalMinute({bucket_minutes})) AS bucket, "
        "count() AS events, max(timestamp) AS newest, now() AS measured_at "
        "FROM events "
        "WHERE timestamp >= now() - toIntervalMinute({window_minutes}) AND timestamp <= now() "
    )
    if event:
        query += "AND event = {event} "
    response = execute_hogql_query(
        query=query + "GROUP BY bucket ORDER BY bucket",
        team=team,
        placeholders={
            "event": ast.Constant(value=event),
            "bucket_minutes": ast.Constant(value=FRESHNESS_BUCKET_MINUTES),
            "window_minutes": ast.Constant(value=FRESHNESS_WINDOW_MINUTES),
        },
    )
    rows = response.results or []
    if not rows:
        # Without a row the query returns no `now()` either, so the age is measured from this clock.
        return datetime.now(team.timezone_info), None, {}
    return rows[0][3], rows[-1][2], {row[0]: int(row[1]) for row in rows}


def _fill_gaps(measured_at: datetime, counts: dict[datetime, int]) -> list[tuple[datetime, int]]:
    """Every bucket from the first one with events to the measurement, with zero where no event landed.

    The empty buckets at the end are the clearest sign of lag, so they have to be shown and not skipped.
    """
    filled = []
    start = min(counts)
    while start <= measured_at:
        filled.append((start, counts.get(start, 0)))
        start += timedelta(minutes=FRESHNESS_BUCKET_MINUTES)
    return filled


def _format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M %Z").strip()


def _format_minutes(minutes: int) -> str:
    if minutes < 1:
        return "under 1 minute"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
