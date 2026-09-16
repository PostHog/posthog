"""Contract types for alerts.

Framework-free types that describe what this product hands to its consumers and
accepts back. No Django, no DRF: other products read against these, and the Turbo
contract check watches this file to decide whether they must retest.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final, NotRequired, TypedDict
from uuid import UUID

from posthog.dataclasses import frozen


class SourceKind(StrEnum):
    LOGS = "logs"
    INSIGHT = "insight"


@frozen
class DemandDiscoveryInputs:
    cutoff: str


@frozen
class AlertDemand:
    configuration_ids_by_source: dict[SourceKind, list[str]]


@frozen
class SourceDispatchInputs:
    """Everything the tick knows about one source. The dispatcher decides how much of it to take."""

    tick_id: str
    source: SourceKind
    page: int
    configuration_ids: list[str]


@frozen
class SourceDispatchReport:
    source: SourceKind
    page: int
    dispatched: int
    remaining_ids: list[str]
    evaluation_workflow_id: str | None


@frozen
class TickPage:
    page: int
    run_id: str
    dispatched: int
    remaining: int


@frozen
class OrchestrateInputs:
    """Empty on the first run. A continued run carries the tick's cutoff, deadline, demand and pages."""

    cutoff: str | None = None
    deadline: str | None = None
    page: int = 0
    demand: dict[SourceKind, list[str]] | None = None
    pages: list[TickPage] | None = None


@frozen
class OrchestrateResult:
    pages: list[TickPage]
    remaining: int
    deadline_reached: bool


class DestinationType(StrEnum):
    SLACK = "slack"
    DISCORD = "discord"
    WEBHOOK = "webhook"
    TEAMS = "teams"

    @property
    def label(self) -> str:
        """Name for this type in a message a person reads."""
        return _DESTINATION_TYPE_LABELS[self]


_DESTINATION_TYPE_LABELS: Final[dict[DestinationType, str]] = {
    DestinationType.SLACK: "Slack",
    DestinationType.DISCORD: "Discord",
    DestinationType.WEBHOOK: "Webhook",
    DestinationType.TEAMS: "Microsoft Teams",
}

# A type without a label would only surface as a KeyError inside a validation message a
# person reads, so a new member without one fails the import instead.
if _DESTINATION_TYPE_LABELS.keys() != set(DestinationType):
    raise RuntimeError("Every DestinationType needs an entry in _DESTINATION_TYPE_LABELS.")


class AlertDestinationData(TypedDict):
    type: DestinationType
    slack_workspace_id: NotRequired[int]
    slack_channel_id: NotRequired[str]
    slack_channel_name: NotRequired[str]
    webhook_url: NotRequired[str]


class AlertDestinationValidationError(Exception):
    """A destination payload the platform refuses. Callers at an HTTP boundary translate
    this into their own framework's validation error."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.message = message
        self.field = field
        super().__init__(message)


@frozen
class AlertDestinationAction:
    url: str
    label: str


@frozen
class EventKindSpec:
    """Everything one alert event kind (firing, resolved, ...) says in a notification."""

    event_id: str
    display_kind: str
    header: str
    details: tuple[tuple[str, str], ...]
    primary_action_url: str
    primary_action_label: str
    webhook_body: dict[str, Any]
    product_label: str = "alert"
    intro_lines: tuple[str, ...] = ()
    additional_actions: tuple[AlertDestinationAction, ...] = ()

    def destination_description(self, alert_name: str) -> str:
        return f'Sends {self.display_kind} notifications for {self.product_label} "{alert_name}".'


@frozen
class AlertDestinationConfig:
    """One destination, built and ready to persist as a HogFunction."""

    payload: dict[str, Any]


@frozen
class AlertDestinationGroup:
    """The HogFunctions that together make up one destination a person configured."""

    hog_function_ids: tuple[UUID, ...]
    data: AlertDestinationData
    fully_enabled: bool


@frozen
class OwnedAlertDestination:
    """One alert-owned HogFunction row, as much of it as a consumer may read."""

    hog_function_id: UUID
    template_id: str | None
    filters: dict[str, Any] | None


@frozen
class ActiveAlertDestination:
    id: str
    name: str
    destination_type: str | None


@frozen
class AlertDelivery:
    """Receipt for one destination that accepted a send. `status` is an open set, so a
    future transport can report an outcome other than "accepted"."""

    channel: str  # "email" | "hog_function"
    target: str  # email address or destination name
    target_id: str | None = None  # hog function id
    template: str | None = None  # "slack" | "discord" | "webhook" | "teams"
    status: str = "accepted"
    at: str  # ISO-8601 timestamp
