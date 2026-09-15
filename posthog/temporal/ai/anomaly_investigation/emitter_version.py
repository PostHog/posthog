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

Deliberately unfiltered, like the sibling provenance block: this measures the event's
producers, not the alerted series. A breakdown alert fires on one value, and the mix
still covers them all.
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
from products.event_definitions.backend.models.property_definition import effective_project_id_expr

from ee.hogai.utils.untrusted import as_untrusted_data

logger = structlog.get_logger(__name__)

# Days before the window the mix is compared against. Long enough that a stable producer
# reads as stable, short enough to stay inside the window the detector itself scores.
BASELINE_DAYS = 14
# Version-ish properties on one event are a handful; the cap only trims a pathological
# taxonomy, and each probed property costs one query.
MAX_PROBED_PROPERTIES = 3
# How many values the block can report on. Shares are computed over the whole period, and
# the biggest movers are kept, so a point-release tail past this cap does not skew them.
MAX_QUERIED_VALUES = 25
MAX_DESCRIBED_VALUES = 5
# Event names, property names and version values are all collected text. A real one is far
# shorter than this, so the cap only trims a value written to fill the prompt.
MAX_TEXT_CHARS = 48
# Share movement that marks a boundary rather than ordinary rollout bleed. A producer
# swap moves a value most of the way across; a canary at a few percent does not.
MIN_SHARE_SHIFT = 0.25

_PROPERTY_NAME_HINT = "version"
_UNSET = "unset"
_FENCE_LABEL = "emitter-version"

_GUIDANCE = (
    "How to read this block:\n"
    "- A shifted version means the program writing the metric changed inside the window. Say so\n"
    "  before blaming the measured subject, and treat the two sides of the boundary as two\n"
    "  different measurements rather than one series.\n"
    "- A flat mix rules the producer out, so spend no budget on it.\n"
    "- A version field named in the metric definition is not this measurement: that field is set\n"
    "  by the producer's own body, so it stays flat across exactly the change that matters.\n"
    "- The mix above is unfiltered, so it covers every occurrence of the event. It can include\n"
    "  traffic the alerted series filters out, and every breakdown value when the alert fired on one."
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

    The event name, the property names and the version values are all collected traffic, so
    the measured lines go inside the shared untrusted-data fence. The reading guidance stays
    outside it, because that part is ours.
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
        compared: list[str] = []
        for name in properties:
            mixes = _query_version_mix(
                team=team,
                event=event,
                property_name=name,
                window_from=window_from,
                window_to=window_to,
                baseline_from=baseline_from,
            )
            if not _is_comparable(mixes):
                continue
            compared.append(name)
            moved = _shifted_values(mixes)
            if moved:
                shifted[name] = moved
        if not compared:
            return ""
    except Exception:
        logger.warning("anomaly_investigation.emitter_version_failed", exc_info=True)
        return ""

    header = (
        "Emitter version — how the version properties on the alerted event moved inside the "
        f"triggered window ({_describe_window(window_from, window_to)}), against the "
        f"{BASELINE_DAYS} days before it:"
    )
    measured = [f'Event "{_single_line(event)}"']
    if not shifted:
        stable = ", ".join(f"`{_single_line(name)}`" for name in compared)
        measured.append(f"- No version boundary: {stable} held the same mix across both periods.")
    else:
        measured.extend(
            f"- `{_single_line(name)}` changed mix: " + "; ".join(_describe_mix(mix) for mix in mixes)
            for name, mixes in shifted.items()
        )
    fenced = as_untrusted_data(_FENCE_LABEL, measured, source="collected from product traffic")
    return f"{header}\n{fenced}\n{_GUIDANCE}"


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
    """Version-ish properties recorded on ``event``, from the project's own taxonomy.

    Taken from the taxonomy rather than a hardcoded list of names: the producer names its
    own version property, and `$lib_version` is only one of the names it picks.

    Scoped by project, like every other reader of this table: the row is unique per project,
    so the first environment to ingest the pair owns it and keeps its own team id. Filtering
    by team id would miss every other environment of the same project.
    """
    names = (
        EventProperty.objects.alias(effective_project_id=effective_project_id_expr())
        .filter(effective_project_id=team.project_id, event=event, property__icontains=_PROPERTY_NAME_HINT)
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
                value,
                in_window,
                before,
                sum(in_window) OVER () AS window_total,
                sum(before) OVER () AS before_total
            FROM (
                SELECT
                    {version} AS value,
                    countIf(toDate(timestamp) >= toDate({window_from})) AS in_window,
                    countIf(toDate(timestamp) < toDate({window_from})) AS before
                FROM events
                WHERE event = {event}
                    AND toDate(timestamp) >= toDate({baseline_from})
                    AND toDate(timestamp) <= toDate({window_to})
                GROUP BY value
            )
            ORDER BY abs(before / before_total - in_window / window_total) DESC, in_window DESC, before DESC
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
    results = response.results or []
    if not results:
        return []
    # Both totals are window sums over every group, so they count the period rather than the
    # rows the limit returned. Each row carries the same pair.
    window_total = int(results[0][3])
    before_total = int(results[0][4])
    if not window_total or not before_total:
        # One side of the boundary is empty, so no share is comparable — an event that only
        # started being emitted inside the window is not a version change.
        return []
    return [
        _VersionMix(
            value=_single_line(str(row[0] or _UNSET)),
            before_share=int(row[2]) / before_total,
            window_share=int(row[1]) / window_total,
        )
        for row in results
    ]


def _is_comparable(mixes: list[_VersionMix]) -> bool:
    """Whether the mix carries version evidence for both sides of the window.

    An empty mix means one side had no events. A lone unset value means the property is in
    the taxonomy but is not being sent. Neither a boundary nor the absence of one follows
    from either, so the property is left out rather than reported as a mix that held.
    """
    if not mixes:
        return False
    return not (len(mixes) == 1 and mixes[0].value == _UNSET)


def _shifted_values(mixes: list[_VersionMix]) -> list[_VersionMix]:
    """The values whose share moved enough to mark a boundary, largest movement first."""
    moved = [mix for mix in mixes if mix.shift >= MIN_SHARE_SHIFT]
    return sorted(moved, key=lambda mix: mix.shift, reverse=True)[:MAX_DESCRIBED_VALUES]


def _describe_mix(mix: _VersionMix) -> str:
    # No angle bracket: the fence defangs one, which would leave the arrow unreadable.
    return f"{mix.value} went {mix.before_share:.0%} to {mix.window_share:.0%} of events"


def _single_line(text: str) -> str:
    """One short printable line of collected text.

    The fence tells the model to read the block as data. This stops a crafted value from
    also forging the block's own line structure, or from filling the prompt on its own.
    """
    printable = "".join(character if character.isprintable() else " " for character in text)
    collapsed = " ".join(printable.split())
    if len(collapsed) > MAX_TEXT_CHARS:
        return f"{collapsed[:MAX_TEXT_CHARS]}…"
    return collapsed or "unset"


def _describe_window(window_from: date, window_to: date) -> str:
    if window_from == window_to:
        return window_from.isoformat()
    return f"{window_from.isoformat()} to {window_to.isoformat()}"
