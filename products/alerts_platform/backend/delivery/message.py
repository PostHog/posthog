"""What a notification says, built from the rows the evaluation recorded.

Source-agnostic. Every fact comes from an `AnnouncedTransition`, which the platform projects from
a `PlatformAlertEvent`, so a message states what its own check decided however long after the
check it is rendered. A provider turns this into its own body shape.
"""

from typing import Any, Final

from posthog.dataclasses import frozen
from posthog.utils import pluralize

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
)

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
    """One notification, before a provider formats it.

    `headline` and `details` are the copy, and a provider that renders text uses only those. The
    other fields are the facts the copy was written from, for a provider whose body is data.
    """

    headline: str
    details: tuple[MessageDetail, ...]
    configuration_id: str
    alert_name: str
    transition: AnnouncedTransition


def _number(value: float) -> str:
    """A count reads as 300 rather than 300.0, and a rate keeps the digits it needs."""
    return f"{value:g}"


def _threshold(condition: dict[str, Any]) -> str | None:
    operator = condition.get("threshold_operator")
    count = condition.get("threshold_count")
    if operator is None or count is None:
        return None
    return f"{operator} {count}"


def _breach_details(transition: AnnouncedTransition) -> list[MessageDetail]:
    details: list[MessageDetail] = []
    if transition.value is not None:
        details.append(MessageDetail(label="Value", value=_number(transition.value)))
    threshold = _threshold(transition.condition)
    if threshold is not None:
        details.append(MessageDetail(label="Threshold", value=threshold))
    window_minutes = transition.condition.get("window_minutes")
    if window_minutes:
        details.append(MessageDetail(label="Window", value=pluralize(window_minutes, "minute")))
    return details


def _failure_details(transition: AnnouncedTransition, consecutive_failures: int) -> list[MessageDetail]:
    details: list[MessageDetail] = []
    if transition.error_message:
        details.append(MessageDetail(label="Error", value=transition.error_message))
    if consecutive_failures:
        details.append(MessageDetail(label="Failed checks", value=str(consecutive_failures)))
    return details


def build_message(announcement: EvaluationAnnouncement, transition: AnnouncedTransition) -> AlertMessage:
    """The message for one transition.

    The announcement carries what the whole evaluation decided, the transition what one group
    did. One message per transition: what a message says about several groups at once is a copy
    decision nobody has made, and it arrives with fan-in rather than being guessed at here.
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
        headline=headline.format(name=announcement.alert_name),
        details=tuple(details),
        configuration_id=announcement.configuration_id,
        alert_name=announcement.alert_name,
        transition=transition,
    )
