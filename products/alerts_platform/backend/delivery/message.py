"""What a notification says, built from the rows the evaluation recorded.

Every fact comes from an `AnnouncedTransition`, which the platform projects from a
`PlatformAlertEvent`, so a message states what its own check decided however long after the check
it is rendered. A source can word parts of it in its own vocabulary through a registered describer.
A provider turns this into its own body shape.
"""

from typing import Any, Final

from posthog.dataclasses import frozen
from posthog.utils import absolute_uri, pluralize

from products.alerts_platform.backend.delivery.describers import describe
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    IncidentAction,
    MessageDetail,
    MessageLink,
    SourceKind,
)

_HEADLINES: Final[dict[AlertEventKind, str]] = {
    AlertEventKind.FIRING: "{kind} alert '{name}' is firing",
    AlertEventKind.RESOLVED: "{kind} alert '{name}' is resolved",
    AlertEventKind.ERRORED: "{kind} alert '{name}' could not be checked",
    AlertEventKind.BROKEN: "{kind} alert '{name}' is turned off",
}

# The symbols the legacy messages use, so a pilot team sees the same state at a glance on both paths.
_SYMBOLS: Final[dict[AlertEventKind, str]] = {
    AlertEventKind.FIRING: "🔴",
    AlertEventKind.RESOLVED: "🟢",
    AlertEventKind.ERRORED: "🟡",
    AlertEventKind.BROKEN: "⚠️",
}

_SOURCE_LABELS: Final[dict[SourceKind, str]] = {
    SourceKind.LOGS: "Log",
    SourceKind.INSIGHT: "Insight",
}

# What a held row says, when cooldown or mute kept its announcement and only its incident moved.
_INCIDENT_KINDS: Final[dict[IncidentAction, AlertEventKind]] = {
    IncidentAction.TRIGGER: AlertEventKind.FIRING,
    IncidentAction.RESOLVE: AlertEventKind.RESOLVED,
}


@frozen
class AlertMessage:
    """One notification, before a provider formats it.

    `headline`, `details`, `context` and the links are the copy, and a provider that renders text
    uses only those. `symbol` marks the state for a reader, and a provider whose body is data
    leaves it out. The other fields are the facts the copy was written from. `incident_action` is
    set only on a message for an incident manager destination.
    """

    headline: str
    symbol: str
    details: tuple[MessageDetail, ...]
    configuration_id: str
    alert_name: str
    source: SourceKind
    alert_url: str
    transition: AnnouncedTransition
    context: tuple[str, ...] = ()
    data_link: MessageLink | None = None
    incident_action: IncidentAction | None = None

    @property
    def title(self) -> str:
        """The headline with its state symbol, for a provider a person reads."""
        return f"{self.symbol} {self.headline}"

    @property
    def links(self) -> tuple[MessageLink, ...]:
        """The source's data first, because that is where a responder starts."""
        view_alert = MessageLink(label="View alert", url=self.alert_url)
        return (self.data_link, view_alert) if self.data_link is not None else (view_alert,)


def state_symbol(kind: AlertEventKind) -> str:
    """The symbol a message about `kind` leads with, so an edited root matches its own messages."""
    return _SYMBOLS[kind]


def alert_url(project_id: int, configuration_id: str) -> str:
    # pinned: the platform alert page route in products/alerts_platform/manifest.tsx.
    return absolute_uri(f"/project/{project_id}/platform-alerts/{configuration_id}")


def _number(value: float) -> str:
    """A count reads as 300 rather than 300.0, and a rate keeps the digits it needs."""
    return f"{value:g}"


def _threshold(condition: dict[str, Any]) -> str | None:
    operator = condition.get("threshold_operator")
    count = condition.get("threshold_count")
    if operator is None or count is None:
        return None
    return f"{operator} {count}"


def _breach_details(transition: AnnouncedTransition) -> tuple[MessageDetail, ...]:
    details: list[MessageDetail] = []
    if transition.value is not None:
        details.append(MessageDetail(label="Value", value=_number(transition.value)))
    threshold = _threshold(transition.condition)
    if threshold is not None:
        details.append(MessageDetail(label="Threshold", value=threshold))
    window_minutes = transition.condition.get("window_minutes")
    if window_minutes:
        details.append(MessageDetail(label="Window", value=pluralize(window_minutes, "minute")))
    return tuple(details)


def _failure_details(transition: AnnouncedTransition, consecutive_failures: int) -> tuple[MessageDetail, ...]:
    details: list[MessageDetail] = []
    if transition.error_message:
        details.append(MessageDetail(label="Error", value=transition.error_message))
    if consecutive_failures:
        details.append(MessageDetail(label="Failed checks", value=str(consecutive_failures)))
    return tuple(details)


def build_message(
    announcement: EvaluationAnnouncement,
    transition: AnnouncedTransition,
    *,
    team_id: int,
    incident_action: IncidentAction | None = None,
    overflowed: int = 0,
) -> AlertMessage:
    """The message for one transition.

    The announcement carries what the whole evaluation decided, the transition what one group
    did. One message per transition: what a message says about several groups at once is a copy
    decision nobody has made, and it arrives with fan-in rather than being guessed at here.
    """
    kind = transition.kind
    if kind == AlertEventKind.CHECK and incident_action is not None:
        kind = _INCIDENT_KINDS[incident_action]
    headline = _HEADLINES.get(kind)
    if headline is None:
        # `announcement` returns a check row only for a group whose incident moved, so a check
        # here without an incident action means that filter is gone.
        raise ValueError(f"{transition.kind} announces nothing and has no message")

    # Platform rows live on the project's root team, so its id is the project id.
    project_id = team_id
    description = describe(announcement.source, project_id=project_id, transition=transition)
    failure_kinds = (AlertEventKind.ERRORED, AlertEventKind.BROKEN)
    if transition.kind in failure_kinds:
        details = list(_failure_details(transition, announcement.consecutive_failures))
    else:
        details = list(description.details or _breach_details(transition))
    if overflowed:
        details.append(
            MessageDetail(
                label="Untracked groups",
                value=f"{pluralize(overflowed, 'more group')} not tracked because this alert is at its group limit",
            )
        )
    return AlertMessage(
        headline=headline.format(kind=_SOURCE_LABELS[announcement.source], name=announcement.alert_name),
        symbol=_SYMBOLS[kind],
        details=tuple(details),
        configuration_id=announcement.configuration_id,
        alert_name=announcement.alert_name,
        source=announcement.source,
        alert_url=alert_url(project_id, announcement.configuration_id),
        transition=transition,
        context=description.context,
        data_link=description.data_link,
        incident_action=incident_action,
    )
