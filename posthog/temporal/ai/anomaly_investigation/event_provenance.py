"""Facts about who emits the alerted event, measured from the event stream.

The metric definition block names the event the alerted series counts, but an event
name says nothing about how the event is produced. A series called "AI summaries"
reads as the output of a backend pipeline, and is just as often a per-person action
recorded from a request handler. With no evidence either way the investigation agent
fills the gap from the name, then recommends checking queue depth, worker errors and
model rate limits on infrastructure that does not exist.

Actor cardinality settles it: an event that thousands of separate actors emit does not
come from one background job, whichever SDK sent it. The numbers are cheap, so they go
into the agent's first message instead of costing it a tool call.

Deliberately unfiltered — this describes the event, not the alerted series.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.dataclasses import frozen
from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.temporal.ai.anomaly_investigation.metric_definition import unwrap_query_source

logger = structlog.get_logger(__name__)


@frozen
class _LibProvenance:
    """Per-SDK emission counts for one event: how much one `$lib` sent, and by how many actors."""

    lib: str
    events: int
    actors: int

PROVENANCE_WINDOW_DAYS = 7
# `$lib` cardinality for a single event is a handful of values, so this only ever trims
# a long tail. The block says when it trimmed one.
MAX_DESCRIBED_LIBS = 6

_GUIDANCE = (
    "How to read this block:\n"
    "- Distinct actors is the ground truth about the emitter. Thousands of separate actors do not\n"
    "  come from one background job, one worker pool or one pipeline, whatever the event name\n"
    "  suggests. A handful of actors emitting a large volume is the shape a system process makes.\n"
    "- `$lib` names the SDK that sent the event, not the reason it was sent. A server-side SDK\n"
    "  records what a person did in a request handler as often as it reports a background job, so\n"
    "  it does not on its own make the event a system event.\n"
    "- The counts above are unfiltered, so they can differ from the alerted series."
)


def alerted_series_event(query: Any, *, series_index: int = 0) -> str | None:
    """The event name the alerted series counts, or None when there isn't a single one.

    Returns None for actions, warehouse tables, SQL insights and the null-event node that
    matches every event — none of those name one event whose emitter can be measured.
    """
    try:
        source = unwrap_query_source(query)
        if not source:
            return None
        series = source.get("series")
        if not isinstance(series, list) or not 0 <= series_index < len(series):
            return None
        node = series[series_index]
        if not isinstance(node, dict) or node.get("kind") != "EventsNode":
            return None
        event = node.get("event")
        return event if isinstance(event, str) and event else None
    except Exception:
        logger.warning("anomaly_investigation.alerted_series_event_failed", exc_info=True)
        return None


def describe_event_provenance(*, team: Team, event: str) -> str:
    """A plain-text block counting the actors that emit ``event``, broken down by SDK.

    Never raises, and returns an empty string when there is nothing to say: this only
    enriches the agent's context, so a failed query must not fail an investigation that
    would otherwise have run.
    """
    try:
        rows = _query_provenance(team=team, event=event)
    except Exception:
        logger.warning("anomaly_investigation.event_provenance_failed", exc_info=True)
        return ""
    if not rows:
        return ""

    lines = [
        f'Event provenance — who emits event "{event}", measured over the last {PROVENANCE_WINDOW_DAYS} days:',
    ]
    lines.extend(f"- {_describe_row(row)}" for row in rows[:MAX_DESCRIBED_LIBS])
    if len(rows) > MAX_DESCRIBED_LIBS:
        lines.append(f"- ({len(rows) - MAX_DESCRIBED_LIBS} further `$lib` values omitted.)")
    lines.append(_GUIDANCE)
    return "\n".join(lines)


def _query_provenance(*, team: Team, event: str) -> list[_LibProvenance]:
    response = execute_hogql_query(
        query=(
            "SELECT properties.$lib AS lib, count() AS events, uniq(distinct_id) AS actors "
            "FROM events "
            "WHERE event = {event} AND timestamp >= now() - toIntervalDay({days}) "
            "GROUP BY lib ORDER BY events DESC LIMIT {limit}"
        ),
        team=team,
        placeholders={
            "event": ast.Constant(value=event),
            "days": ast.Constant(value=PROVENANCE_WINDOW_DAYS),
            "limit": ast.Constant(value=MAX_DESCRIBED_LIBS + 1),
        },
    )
    return [
        _LibProvenance(lib=str(row[0] or "unset"), events=int(row[1]), actors=int(row[2]))
        for row in response.results or []
    ]


def _describe_row(row: _LibProvenance) -> str:
    return (
        f"`$lib` {row.lib}: {row.events:,} events from {row.actors:,} distinct actors "
        f"({row.events / row.actors:.1f} events per actor)"
    )
