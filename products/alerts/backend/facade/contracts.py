"""Contract types for alerts.

Framework-free types that describe what this product hands to its consumers and
accepts back. No Django, no DRF: other products read against these, and the Turbo
contract check watches this file to decide whether they must retest.
"""

from __future__ import annotations

from dataclasses import field
from datetime import datetime
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
class AlertBatchKey:
    """Names a chunk of due work by what it holds rather than by where it was cut.

    `slot` is `next_check_at` floored to the minute, so a chunk keeps its identity across ticks:
    a slow evaluation of a key is still the same key when the next tick rediscovers it.
    """

    team_id: int
    slot: str


@frozen
class AlertDemand:
    """Due batch keys per source, bounded so the payload stays small. A key costs a fixed amount and
    does not grow with a team's alert count. `omitted_by_source` counts keys discovery left out;
    that work is due again next tick."""

    batch_keys_by_source: dict[SourceKind, list[AlertBatchKey]]
    omitted_by_source: dict[SourceKind, int] = field(default_factory=dict)


@frozen
class SourceDispatchInputs:
    """Everything the tick knows about one source. The dispatcher decides how much of it to take."""

    tick_id: str
    source: SourceKind
    page: int
    batch_keys: list[AlertBatchKey]
    cutoff: str


@frozen
class SourceDispatchReport:
    source: SourceKind
    page: int
    dispatched: int
    remaining_keys: list[AlertBatchKey]
    evaluation_workflow_ids: list[str]
    # Not remaining: the run that already holds the key is still working it.
    already_running: int = 0


@frozen
class SourceEvaluationInputs:
    """What a source's own evaluation workflow receives from its dispatcher.

    The key, not a list of ids. The evaluation loads full configurations anyway, so shipping ids
    through the orchestrator would be transit cost, and re-reading gives it the fresher set.
    """

    source: SourceKind
    cutoff: str
    batch_key: AlertBatchKey


@frozen
class PlatformAlertCheck:
    """One configuration and its runtime state, as a source adapter reads it.

    Flat rather than nested, because a source never holds the rows and has nothing to do with
    the split between what belongs to the configuration and what belongs to the instance.
    """

    id: UUID
    team_id: int
    name: str
    source_config: dict[str, Any]
    threshold_count: int
    threshold_operator: str
    window_minutes: int
    check_interval_minutes: int
    evaluation_periods: int
    datapoints_to_alarm: int
    cooldown_minutes: int
    schedule_restriction: dict[str, Any] | None
    next_check_at: datetime | None
    consecutive_failures: int
    legacy_configuration_id: UUID | None
    state: str
    last_notified_at: datetime | None
    snooze_until: datetime | None

    @property
    def filters(self) -> dict[str, Any]:
        """Satisfies the logs query layer, which names this field `filters`."""
        return self.source_config


@frozen
class PlatformAlertUpsert:
    """One configuration a source wants copied into the shared tables."""

    legacy_configuration_id: UUID
    team_id: int
    name: str
    enabled: bool
    source_kind: SourceKind
    source_config: dict[str, Any]
    threshold_count: int
    threshold_operator: str
    window_minutes: int
    check_interval_minutes: int
    evaluation_periods: int
    datapoints_to_alarm: int
    cooldown_minutes: int
    schedule_restriction: dict[str, Any] | None
    next_check_at: datetime | None


@frozen
class PlatformAlertOutcome:
    """What one check decided. The platform turns this into rows."""

    configuration_id: UUID
    new_state: str
    notified: bool
    consecutive_failures: int
    # Recording an outcome without it leaves a configuration discovery keeps handing back to an
    # evaluation that cannot succeed.
    disable: bool = False


@frozen
class GroupTransition:
    """One transition a delivery would carry. `grouping_key` is empty until a source groups,
    so delivery reads a list of one today and a list of N when fan-out ships."""

    grouping_key: str
    notification: str


@frozen
class AlertDeliveryPreview:
    """What delivery would send. The PoC records it instead of contacting a destination."""

    source: SourceKind
    alert_id: str
    alert_name: str
    evaluation_key: str
    destination_names: tuple[str, ...]
    transitions: tuple[GroupTransition, ...]


@frozen
class SourceBatchEvaluation:
    """What one batch decided, before any of it is written.

    Evaluation returns this and the write runs as its own activity, so Temporal has the
    deliveries in history before anything can advance a schedule past them.
    """

    outcomes: tuple[PlatformAlertOutcome, ...]
    previews: tuple[AlertDeliveryPreview, ...]
    # Pairs the payload bound left out. They keep their due time and a later tick re-evaluates
    # them, the way a truncated cohort already behaves.
    omitted: int = 0


# The platform's write, which a source's evaluation workflow starts by name. One definition,
# because a rename that misses a source breaks it at runtime and nothing else would catch it.
RECORD_OUTCOMES_ACTIVITY: Final[str] = "alerts_product_record_outcomes"


@frozen
class SourceOutcomeInputs:
    team_id: int
    cutoff: str
    outcomes: tuple[PlatformAlertOutcome, ...]


@frozen
class TickPage:
    page: int
    run_id: str
    dispatched: int
    remaining: int
    # Sources whose dispatcher failed on this page, and the keys they never took. Those keys keep
    # their due time, so a later tick rediscovers them; the page reports them rather than ending
    # the tick.
    failed_sources: int = 0
    undispatched: int = 0


@frozen
class OrchestrateInputs:
    """Empty on the first run. A continued run carries the tick's cutoff, deadlines, demand and pages."""

    cutoff: str | None = None
    deadline: str | None = None  # stop starting pages after this
    hard_deadline: str | None = None  # the execution timeout lands here; no page may run past it
    page: int = 0
    demand: dict[SourceKind, list[AlertBatchKey]] | None = None
    pages: list[TickPage] | None = None
    omitted: int = 0  # due work discovery left out of the bounded manifest; counted as remaining


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
