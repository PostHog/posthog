"""Explain why an event-filtered recordings search came back empty.

Recordings join events on `properties.$session_id`, so events captured without replay
context match no recording however the filters are set.
"""

from enum import StrEnum

from posthog.dataclasses import frozen

UNLINKED_COVERAGE_THRESHOLD = 0.1
SESSION_ID_DOCS_URL = "https://posthog.com/docs/data/sessions#server-sdks-and-sessions"


class EmptyResultCause(StrEnum):
    NO_EVENTS = "no_events"
    EVENTS_NOT_LINKED = "events_not_linked"
    RECORDING_DISABLED = "recording_disabled"
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
class SearchScope:
    """The parts of an event-less search that decide whether any recording can match."""

    date_from: str
    date_to: str | None
    filter_test_accounts: bool


@frozen
class EmptyResultDiagnosis:
    cause: EmptyResultCause
    linkages: tuple[EventSessionLinkage, ...]


def diagnose(
    linkages: tuple[EventSessionLinkage, ...], *, match_any: bool, recording_enabled: bool
) -> EmptyResultDiagnosis:
    # One failing filter empties an AND search; every filter has to fail for an OR search.
    fails = all if match_any else any
    present = tuple(linkage for linkage in linkages if linkage.total > 0)

    if fails(linkage.total == 0 for linkage in linkages):
        cause = EmptyResultCause.NO_EVENTS
        culprits = tuple(linkage for linkage in linkages if linkage.total == 0)
    elif present and fails(linkage.is_unlinked for linkage in present):
        cause = EmptyResultCause.EVENTS_NOT_LINKED
        culprits = tuple(linkage for linkage in present if linkage.is_unlinked)
    elif not recording_enabled:
        cause = EmptyResultCause.RECORDING_DISABLED
        culprits = present
    else:
        cause = EmptyResultCause.FILTERS_TOO_NARROW
        culprits = present
    return EmptyResultDiagnosis(cause=cause, linkages=culprits)


def describe(diagnosis: EmptyResultDiagnosis) -> str:
    """Guidance for the agent, not text to show verbatim."""
    names = ", ".join(f"`{linkage.event}`" for linkage in diagnosis.linkages)

    if diagnosis.cause == EmptyResultCause.NO_EVENTS:
        return (
            f"\n\nDiagnosis: no {names} events matched this filter in the date range, so there was nothing to "
            "match recordings against. Tell the user the search could not run rather than that no users did this. "
            "Suggest checking the event name and its property filters, widening the date range, or instrumenting "
            "the event. Do not offer a Replay Vision scanner."
        )

    if diagnosis.cause == EmptyResultCause.EVENTS_NOT_LINKED:
        counts = ", ".join(
            f"`{linkage.event}` ({linkage.total} events, {linkage.coverage:.0%} carrying a session id)"
            for linkage in diagnosis.linkages
        )
        return (
            f"\n\nDiagnosis: {counts}. Recordings are matched to events through `$session_id`, so these events "
            "cannot match any recording however the filters are set. This is the usual shape when a mobile or "
            "server-side SDK captures events without session replay context. Tell the user the events are not "
            "linked to recordings, and be explicit that this does not mean the behavior did not happen. Then offer "
            "both: a Replay Vision scanner, which finds the behavior by watching the recordings instead of by "
            f"matching events, and linking the events to recordings as the durable fix, see {SESSION_ID_DOCS_URL}."
        )

    if diagnosis.cause == EmptyResultCause.RECORDING_DISABLED:
        return (
            f"\n\nDiagnosis: {names} events exist and carry session ids, but session replay is disabled for this "
            "project, so no recordings were captured. Suggest enabling session replay in project settings. "
            "Do not offer a Replay Vision scanner."
        )

    return (
        f"\n\nDiagnosis: {names} events exist and are linked to recordings, so the cause is elsewhere: another "
        "filter, the replay sample rate or minimum duration, or retention. Suggest widening the date range or "
        "dropping a filter. Do not offer a Replay Vision scanner."
    )


def describe_scope(scope: SearchScope, *, recording_enabled: bool) -> str:
    """Guidance for a search that named no event, so event linkage cannot be the cause."""
    if not recording_enabled:
        return (
            "\n\nDiagnosis: session replay is disabled for this project, so no recordings were captured. "
            "Suggest enabling session replay in project settings. Do not offer a Replay Vision scanner."
        )

    accounts = "excluded test accounts" if scope.filter_test_accounts else "included test accounts"
    return (
        "\n\nDiagnosis: this search named no event, so only the date range and the remaining filters decide "
        f"the result. It covered {scope.date_from} to {scope.date_to or 'now'} and {accounts}. The user did not "
        "necessarily choose either, so name the date range and the filters the search used instead of reporting "
        "a bare empty result. Say that no recording in that range matched, not that the behavior never happened. "
        "Suggest widening the date range first, then dropping a filter. Do not offer a Replay Vision scanner."
    )
