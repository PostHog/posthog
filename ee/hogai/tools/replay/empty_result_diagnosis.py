"""Explain why an event-filtered recordings search came back empty.

Recordings are matched to events through `properties.$session_id`, and the events
subquery drops any event where that is empty. An event stream captured without
replay context therefore matches no recording however the filters are set, and
looks identical to "this behavior never happened". These helpers tell the two
apart so the agent can answer with the real cause.
"""

from enum import StrEnum

from posthog.dataclasses import frozen

# Under this share of events carrying a session id, the join has essentially nothing
# to match on, so an empty result reveals nothing about what users actually did.
UNLINKED_COVERAGE_THRESHOLD = 0.1


class EmptyResultCause(StrEnum):
    NO_EVENTS = "no_events"
    EVENTS_NOT_LINKED = "events_not_linked"
    FILTERS_TOO_NARROW = "filters_too_narrow"


@frozen
class EventSessionLinkage:
    event: str
    total: int
    linked: int

    @property
    def coverage(self) -> float:
        return self.linked / self.total if self.total else 0.0

    @property
    def is_unlinked(self) -> bool:
        return self.total > 0 and self.coverage < UNLINKED_COVERAGE_THRESHOLD


@frozen
class EmptyResultDiagnosis:
    cause: EmptyResultCause
    linkages: tuple[EventSessionLinkage, ...]


def diagnose(linkages: tuple[EventSessionLinkage, ...]) -> EmptyResultDiagnosis:
    if not linkages or all(linkage.total == 0 for linkage in linkages):
        cause = EmptyResultCause.NO_EVENTS
    elif any(linkage.is_unlinked for linkage in linkages):
        # One unlinked event is enough: under AND it alone empties the result, and
        # under OR it still contributes nothing, so it is worth surfacing either way.
        cause = EmptyResultCause.EVENTS_NOT_LINKED
    else:
        cause = EmptyResultCause.FILTERS_TOO_NARROW
    return EmptyResultDiagnosis(cause=cause, linkages=linkages)


def describe(diagnosis: EmptyResultDiagnosis) -> str:
    """Render the diagnosis as guidance for the agent, not as text to show verbatim."""
    if diagnosis.cause == EmptyResultCause.NO_EVENTS:
        names = ", ".join(f"`{linkage.event}`" for linkage in diagnosis.linkages)
        return (
            f"\n\nDiagnosis: this project received no {names} events in this date range, so there was nothing to "
            "match recordings against. Tell the user the search could not run rather than that no users did this. "
            "Suggest checking the event name, widening the date range, or instrumenting the event. "
            "Do not offer a Replay Vision scanner."
        )

    if diagnosis.cause == EmptyResultCause.EVENTS_NOT_LINKED:
        unlinked = [linkage for linkage in diagnosis.linkages if linkage.is_unlinked]
        counts = ", ".join(
            f"`{linkage.event}` ({linkage.total} events, {linkage.coverage:.0%} carrying a session id)"
            for linkage in unlinked
        )
        return (
            f"\n\nDiagnosis: {counts}. Recordings are matched to events through `$session_id`, so these events "
            "cannot match any recording however the filters are set. This is the usual shape when a mobile or "
            "server-side SDK captures events without session replay context. Tell the user the events are not "
            "linked to recordings, and be explicit that this does not mean the behavior did not happen. Then offer "
            "both: a Replay Vision scanner, which finds the behavior by watching the recordings instead of by "
            "matching events, and linking the events to recordings as the durable fix."
        )

    return (
        "\n\nDiagnosis: the filtered events exist and are linked to recordings, so the filters are simply too "
        "narrow. Suggest widening the date range or dropping a filter. Do not offer a Replay Vision scanner."
    )
