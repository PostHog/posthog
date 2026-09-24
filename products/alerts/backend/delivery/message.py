"""What a notification says, built from the rows the evaluation recorded.

Source-agnostic. Every fact comes from a `GroupTransition`, which the platform projects from a
`PlatformAlertEvent`, so a message states what its own check decided however long after the
check it is rendered. A provider turns this into its own body shape.
"""

from typing import Any, Final

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import AlertEventKind, EvaluationAnnouncement, GroupTransition

_HEADLINES: Final[dict[AlertEventKind, str]] = {
    AlertEventKind.FIRING: "{name} is firing",
    AlertEventKind.RESOLVED: "{name} is resolved",
    AlertEventKind.ERRORED: "{name} could not be checked",
    AlertEventKind.BROKEN: "{name} is turned off",
}


@frozen
class MessageDetail:
    """One labelled fact in a message. Every provider renders these the same way, as a Slack
    section, an Adaptive Card body, or lines of markdown."""

    label: str
    value: str


@frozen
class AlertMessage:
    """One notification, before a provider formats it."""

    headline: str
    details: tuple[MessageDetail, ...]
    kind: AlertEventKind


def _number(value: float) -> str:
    """A count reads as 300 rather than 300.0, and a rate keeps the digits it needs."""
    return f"{value:g}"


def _minutes(count: int) -> str:
    return f"{count} minute" if count == 1 else f"{count} minutes"


def _threshold(condition: dict[str, Any]) -> str | None:
    operator = condition.get("threshold_operator")
    count = condition.get("threshold_count")
    if operator is None or count is None:
        return None
    return f"{operator} {count}"


def _breach_details(transition: GroupTransition) -> list[MessageDetail]:
    details: list[MessageDetail] = []
    if transition.value is not None:
        details.append(MessageDetail(label="Value", value=_number(transition.value)))
    threshold = _threshold(transition.condition)
    if threshold is not None:
        details.append(MessageDetail(label="Threshold", value=threshold))
    window_minutes = transition.condition.get("window_minutes")
    if window_minutes:
        details.append(MessageDetail(label="Window", value=_minutes(window_minutes)))
    return details


def _failure_details(transition: GroupTransition, consecutive_failures: int) -> list[MessageDetail]:
    details: list[MessageDetail] = []
    if transition.error_message:
        details.append(MessageDetail(label="Error", value=transition.error_message))
    if consecutive_failures:
        details.append(MessageDetail(label="Failed checks", value=str(consecutive_failures)))
    return details


def build_message(announcement: EvaluationAnnouncement, transition: GroupTransition) -> AlertMessage:
    """The message for one transition.

    The announcement carries what the whole evaluation decided, the transition what one group
    did. One transition rather than a whole `Notification`, because a notification carries one
    transition until a source groups its results. What a message says about several groups at
    once is a copy decision nobody has made, and guessing at it here would put the guess in
    front of users.
    """
    headline = _HEADLINES.get(transition.kind)
    if headline is None:
        # `announcement` excludes the check rows, so every transition that reaches delivery
        # announces something. A check here means that filter is gone.
        raise ValueError(f"{transition.kind} announces nothing and has no message")

    failure_kinds = (AlertEventKind.ERRORED, AlertEventKind.BROKEN)
    details = (
        _failure_details(transition, announcement.consecutive_failures)
        if transition.kind in failure_kinds
        else _breach_details(transition)
    )
    return AlertMessage(
        headline=headline.format(name=announcement.alert_name), details=tuple(details), kind=transition.kind
    )
