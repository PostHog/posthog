"""Whether the alerted event's producer changed version across the triggered window.

A metric whose value is written by a program — an LLM judge's verdict, a classifier's
label, a scorer's band, an SDK's own measurement — moves when that program changes,
with nothing about the measured subject moving at all. The agent cannot see that from
the metric definition or from the series, so it reads a producer change as a change in
what is being produced and sends the reader to fix the wrong thing.

The version the producer stamps on its events settles it. Version properties on the
alerted event are measured inside the triggered window and against the days before it:
a value that takes over the window marks a producer boundary, and a flat mix rules the
explanation out. Both answers are worth the query, so the block states either.

A version field written into the payload by the producer's own body is not this
measurement. That field says what the body believes about itself, so a body that
changes without bumping it reads as stable — which is how a producer change hides.
"""

from __future__ import annotations

from datetime import date, timedelta

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.models import Team

from products.event_definitions.backend.models.event_property import EventProperty

logger = structlog.get_logger(__name__)

# Days before the window the mix is compared against. Long enough that a stable producer
# reads as stable, short enough to stay inside the window the detector itself scores.
BASELINE_DAYS = 14
# Version-ish properties on one event are a handful; the cap only trims a pathological
# taxonomy, and each probed property costs one query.
MAX_PROBED_PROPERTIES = 3
# Well above real version cardinality on a single event. Shares are computed over the
# returned rows, so the cap has to clear the tail rather than land in it.
MAX_QUERIED_VALUES = 25
MAX_DESCRIBED_VALUES = 5
# Share movement that marks a boundary rather than ordinary rollout bleed. A producer
# swap moves a value most of the way across; a canary at a few percent does not.
MIN_SHARE_SHIFT = 0.25

_PROPERTY_NAME_HINT = "version"

_GUIDANCE = (
    "How to read this block:\n"
    "- A shifted version means the program writing the metric changed inside the window. Say so\n"
    "  before blaming the measured subject, and treat the two sides of the boundary as two\n"
    "  different measurements rather than one series.\n"
    "- A flat mix rules the producer out, so spend no budget on it.\n"
    "- A version field named in the metric definition is not this measurement: that field is set\n"
    "  by the producer's own body, so it stays flat across exactly the change that matters."
)


@frozen
class _VersionMix:
    """One version value's share of the alerted event, before the window and inside it."""

    value: str
    before_share: float
    window_share: float

    @property
    def shift(self) -> float:
        return abs(self.window_share - self.before_share)


def describe_emitter_version_shift(*, team: Team, event: str, triggered_dates: list[str]) -> str:
    """A plain-text block on how ``event``'s version properties moved across the window.

    Never raises, and returns an empty string when there is nothing to say: this only
    enriches the agent's context, so a failed query must not fail an investigation that
    would otherwise have run.
    """
    try:
        window = _window_bounds(triggered_dates)
        if window is None:
            return ""
        window_from, window_to = window
        baseline_from = window_from - timedelta(days=BASELINE_DAYS)
        properties = _version_properties(team=team, event=event)
        if not properties:
            return ""
        shifted: dict[str, list[_VersionMix]] = {}
        for name in properties:
            mixes = _query_version_mix(
                team=team,
                event=event,
                property_name=name,
                window_from=window_from,
                window_to=window_to,
                baseline_from=baseline_from,
            )
            moved = _shifted_values(mixes)
            if moved:
                shifted[name] = moved
    except Exception:
        logger.warning("anomaly_investigation.emitter_version_failed", exc_info=True)
        return ""

    header = (
        f'Emitter version — how the version properties on event "{event}" moved inside the '
        f"triggered window ({_describe_window(window_from, window_to)}), against the "
        f"{BASELINE_DAYS} days before it:"
    )
    if not shifted:
        stable = ", ".join(f"`{name}`" for name in properties)
        return f"{header}\n- No version boundary: {stable} held the same mix across both periods.\n{_GUIDANCE}"
    lines = [header]
    for name, mixes in shifted.items():
        lines.append(f"- `{name}` changed mix: " + "; ".join(_describe_mix(mix) for mix in mixes))
    lines.append(_GUIDANCE)
    return "\n".join(lines)


def _window_bounds(triggered_dates: list[str]) -> tuple[date, date] | None:
    """First and last triggered day. ``triggered_dates`` are date-only for a daily alert
    and carry a time for an hourly one, so only the date part is read."""
    days = sorted({parsed for value in triggered_dates if (parsed := _parse_day(value)) is not None})
    return (days[0], days[-1]) if days else None


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _version_properties(*, team: Team, event: str) -> list[str]:
    """Version-ish properties recorded on ``event``, from the team's own taxonomy.

    Taken from the taxonomy rather than a hardcoded list of names: the producer names its
    own version property, and `$lib_version` is only one of the names it picks.
    """
    names = (
        EventProperty.objects.filter(team_id=team.id, event=event, property__icontains=_PROPERTY_NAME_HINT)
        .order_by("property")
        .values_list("property", flat=True)[:MAX_PROBED_PROPERTIES]
    )
    return list(names)


def _query_version_mix(
    *,
    team: Team,
    event: str,
    property_name: str,
    window_from: date,
    window_to: date,
    baseline_from: date,
) -> list[_VersionMix]:
    response = execute_hogql_query(
        query=parse_select(
            """
            SELECT
                {version} AS value,
                countIf(toDate(timestamp) >= toDate({window_from})) AS in_window,
                countIf(toDate(timestamp) < toDate({window_from})) AS before
            FROM events
            WHERE event = {event}
                AND toDate(timestamp) >= toDate({baseline_from})
                AND toDate(timestamp) <= toDate({window_to})
            GROUP BY value
            ORDER BY in_window DESC, before DESC
            LIMIT {limit}
            """,
            placeholders={
                "version": ast.Field(chain=["properties", property_name]),
                "event": ast.Constant(value=event),
                "window_from": ast.Constant(value=window_from.isoformat()),
                "window_to": ast.Constant(value=window_to.isoformat()),
                "baseline_from": ast.Constant(value=baseline_from.isoformat()),
                "limit": ast.Constant(value=MAX_QUERIED_VALUES),
            },
        ),
        team=team,
    )
    rows = [(str(row[0] or "unset"), int(row[1]), int(row[2])) for row in response.results or []]
    window_total = sum(row[1] for row in rows)
    before_total = sum(row[2] for row in rows)
    if not window_total or not before_total:
        # One side of the boundary is empty, so no share is comparable — an event that only
        # started being emitted inside the window is not a version change.
        return []
    return [
        _VersionMix(value=value, before_share=before / before_total, window_share=in_window / window_total)
        for value, in_window, before in rows
    ]


def _shifted_values(mixes: list[_VersionMix]) -> list[_VersionMix]:
    """The values whose share moved enough to mark a boundary, largest movement first."""
    moved = [mix for mix in mixes if mix.shift >= MIN_SHARE_SHIFT]
    return sorted(moved, key=lambda mix: mix.shift, reverse=True)[:MAX_DESCRIBED_VALUES]


def _describe_mix(mix: _VersionMix) -> str:
    return f"{mix.value} went {mix.before_share:.0%} -> {mix.window_share:.0%} of events"


def _describe_window(window_from: date, window_to: date) -> str:
    if window_from == window_to:
        return window_from.isoformat()
    return f"{window_from.isoformat()} to {window_to.isoformat()}"
