"""Contract types for alerts.

Framework-free types that describe what this product hands to its consumers and
accepts back. No Django, no DRF: other products read against these, and the Turbo
contract check watches this file to decide whether they must retest.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, NotRequired, Protocol, TypedDict
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

if TYPE_CHECKING:
    # facade.lifecycle imports this module, so the policy type stays off the runtime import path.
    from products.alerts_platform.backend.facade.lifecycle import AlertPolicy


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


# Where a source keeps its bound inside `source_config`. Each source gives it its own shape and
# the platform interprets none of it: the history row snapshots it, so a reader sees the bound a
# check was evaluated against.
SOURCE_CONDITION_KEY: Final = "condition"


def source_condition(source_config: dict[str, Any]) -> dict[str, Any]:
    """A source's bound, or an empty one when the stored value is missing or not an object."""
    condition = source_config.get(SOURCE_CONDITION_KEY)
    return condition if isinstance(condition, dict) else {}


@frozen
class PlatformAlertCheckInput:
    """One configuration and its runtime state, as a source adapter reads it.

    Flat rather than nested, because a source never holds the rows and has nothing to do with
    the split between what belongs to the configuration and what belongs to the instance.
    """

    id: UUID
    team_id: int
    name: str
    source_config: dict[str, Any]
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
    firing_started_at: datetime | None = None

    @property
    def filters(self) -> dict[str, Any]:
        """Satisfies the logs query layer, which names this field `filters`."""
        return self.source_config

    @property
    def condition(self) -> dict[str, Any]:
        return source_condition(self.source_config)


@frozen
class PlatformAlertUpsert:
    """One configuration a source wants copied into the shared tables."""

    legacy_configuration_id: UUID
    team_id: int
    name: str
    enabled: bool
    source_kind: SourceKind
    source_config: dict[str, Any]
    check_interval_minutes: int
    evaluation_periods: int
    datapoints_to_alarm: int
    cooldown_minutes: int
    schedule_restriction: dict[str, Any] | None
    next_check_at: datetime | None
    snooze_until: datetime | None
    recurrence_unit: str | None = None
    anchor_time: str | None = None


class SkipReason(StrEnum):
    """Why a check reached an outcome without a query answering it.

    A label on the platform's own counters. It never reaches an alert's state or schedule. A check
    that was evaluated has no skip reason, which is `None` rather than a member here.
    """

    BROKEN_CONFIG = "broken_config"
    QUERY_FAILED = "query_failed"


class MuteReason(StrEnum):
    """Why an announcement was held. A muted check is evaluated like any other, so this labels the
    held announcement rather than a skip."""

    SNOOZE = "snooze"
    QUIET_HOURS = "quiet_hours"


class AlertEventKind(StrEnum):
    """What one evaluation announced about an alert.

    `CHECK` is an evaluation that announced nothing, which includes one that moved the alert while
    a cooldown or a mute held the notification back. Read the history row's `previous_state` and
    `state` to find the moves, because counting `RESOLVED` rows misses every recovery that was
    suppressed.

    A source reports the kind rather than the platform deriving it: the machine already decided
    what to announce, and deriving it again from the states would be a second implementation of
    that decision.
    """

    CHECK = "check"
    FIRING = "firing"
    RESOLVED = "resolved"
    ERRORED = "errored"
    BROKEN = "broken"


@frozen
class FiringEpisode:
    """The firing a check concerns, and whether that check is the one that ended it.

    Two readers want different things from it. An alert's current state wants the firing it is in
    now, which is nothing once a check ends one. A history row and a delivery want the firing the
    check was about, which on a resolve is the firing that just ended. Both come from here, so
    neither has to work the difference out from the states.

    `started_at` is None for a firing that began before the platform recorded starts.
    """

    started_at: datetime | None
    ended: bool


@frozen
class PlatformAlertOutcome:
    """What one check decided. The platform turns this into rows.

    Every check produces one, including a check a source skipped. A skip that records nothing
    leaves its due time where it was, so discovery finds the same work every tick.
    """

    configuration_id: UUID
    evaluation_key: str
    kind: AlertEventKind
    new_state: str
    notified: bool
    consecutive_failures: int
    firing_episode: FiringEpisode | None = None
    value: float | None = None
    labels: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    query_duration_ms: int | None = None
    # What a mute held back, so history separates a muted fire from a check that said nothing.
    muted_notification: str = ""
    # Recording an outcome without it leaves a configuration discovery keeps handing back to an
    # evaluation that cannot succeed.
    disable: bool = False


@frozen
class GroupTransition:
    """One transition a delivery carries: `kind` picks the headline, `value` is the number it
    quotes.

    `grouping_key` is empty until a source groups, so delivery reads a list of one today and a
    list of N when fan-out ships.

    The condition and the source config a message also needs stay on the history row the
    delivery addresses, because `source_config` is an unbounded filter tree and one per
    transition would blow the payload bound `MAX_DELIVERIES_PER_CYCLE` was sized against.
    """

    grouping_key: str
    kind: AlertEventKind
    value: float | None = None


@frozen
class AnnouncedTransition:
    """One group's transition as delivery reads it back, projected from a history row.

    The sibling of `GroupTransition`, and deliberately not the same type. A `GroupTransition`
    crosses Temporal on the delivery payload, so it stays small. This never does: delivery holds
    an address, reads the row, and builds one of these in the process that sends the message. So
    it carries what a message states, including the two snapshots the row already keeps.

    Every field here is a column on `platform_alert_events`, which is what makes a message state
    what its own check decided however long after the check it is rendered.
    """

    grouping_key: str
    kind: AlertEventKind
    # The firing this transition concerns, which on a resolve is the firing that just ended.
    # None when no firing is involved, which is a failed or a turned-off check.
    episode_started_at: datetime | None
    value: float | None
    labels: dict[str, str]
    condition: dict[str, Any]
    source_config: dict[str, Any]
    error_message: str | None
    # A resolve states this as the time its firing ended.
    occurred_at: datetime


@frozen
class EvaluationAnnouncement:
    """What one evaluation left for a destination to say.

    One transition is one message. A level between this and the transitions would be the place a
    fan-in policy lived, and fan-in was deprioritized on 2026-09-28, so there is nothing for it
    to hold. It arrives with fan-in rather than waiting here empty.
    """

    configuration_id: str
    alert_name: str
    # Evaluation-level, so it sits here rather than on a transition: a failed check fails the
    # whole evaluation, and every group in one announcement saw the same count.
    consecutive_failures: int
    transitions: tuple[AnnouncedTransition, ...]


@frozen
class AlertDeliveryRequest:
    """Where to find what one evaluation decided, rather than a copy of it.

    A delivery addresses its history rows by `configuration_id` and `evaluation_key`, and reads
    the facts back from there. So a retry announces what was recorded rather than what one
    attempt happened to carry, and a batch's payload does not grow with what its alerts say.

    The two destination fields are supplied by the source because only the source knows them.
    `destination_alert_id` is the id its destinations are matched on, which is the legacy
    configuration while the platform runs beside a source's own stack. `event_ids_by_kind` maps
    each kind the source can announce onto the event id its destinations filter on. The platform
    imports no source, so it cannot derive either.

    `incident_actions` maps a grouping key to whether its transition opened or closed a firing.
    It is a decision rather than a fact a message states, so it travels here like
    `event_ids_by_kind`. It is set even when cooldown or mute held the announcement back, which
    is the case it exists for. `sends_messages` is False on a delivery that exists only for those
    actions, so its rows reach no message destination even when their kind has an event id.
    `event_ids_by_incident_action` maps each action onto the event id an incident manager
    destination filters on, the way `event_ids_by_kind` does for a message.
    """

    source: SourceKind
    team_id: int
    configuration_id: str
    evaluation_key: str
    destination_alert_id: str
    event_ids_by_kind: dict[str, str]
    incident_actions: dict[str, IncidentAction] = field(default_factory=dict)
    sends_messages: bool = True
    event_ids_by_incident_action: dict[str, str] = field(default_factory=dict)


@frozen
class SourceBatchEvaluation:
    """What one batch decided, before any of it is written.

    Evaluation returns this and the write runs as its own activity, so Temporal has the
    deliveries in history before anything can advance a schedule past them.
    """

    outcomes: tuple[PlatformAlertOutcome, ...]
    deliveries: tuple[AlertDeliveryRequest, ...]
    # Pairs the payload bound left out. They keep their due time and a later tick re-evaluates
    # them, the way a truncated cohort already behaves.
    omitted: int = 0


# The platform's write, which a source's evaluation workflow starts by name. One definition,
# because a rename that misses a source breaks it at runtime and nothing else would catch it.
RECORD_OUTCOMES_ACTIVITY: Final[str] = "alerts_platform_record_outcomes"


@frozen
class PlatformConfigurationSnapshot:
    """A configuration as a source's own test reads it back, without holding the row."""

    id: UUID
    next_check_at: datetime | None
    consecutive_failures: int


@frozen
class PlatformAlertSnapshot:
    """One instance's runtime state, for a reader outside this product."""

    id: UUID
    grouping_key: str
    state: str
    firing_started_at: datetime | None
    last_notified_at: datetime | None
    snooze_until: datetime | None


@frozen
class PlatformAlertConfigurationView:
    """One configuration and its instances, as a reader outside this product sees them.

    The instances arrive with it because a reader asking for a configuration always wants its
    runtime state, and fetching them separately would be one query per configuration.
    """

    id: UUID
    name: str
    enabled: bool
    source_kind: str
    source_config: dict[str, Any]
    check_interval_minutes: int
    recurrence_unit: str | None
    anchor_time: str | None
    evaluation_periods: int
    datapoints_to_alarm: int
    cooldown_minutes: int
    schedule_restriction: dict[str, Any] | None
    next_check_at: datetime | None
    consecutive_failures: int
    legacy_configuration_id: UUID | None
    created_at: datetime
    updated_at: datetime
    alerts: tuple[PlatformAlertSnapshot, ...]


@frozen
class PlatformAlertConfigurationPage:
    """One page of configurations, with the total the reader needs to paginate."""

    configurations: tuple[PlatformAlertConfigurationView, ...]
    total: int


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


class DestinationType(LabeledStrEnum):
    # The label names the type in a message a person reads.
    SLACK = "slack", "Slack"
    DISCORD = "discord", "Discord"
    WEBHOOK = "webhook", "Webhook"
    TEAMS = "teams", "Microsoft Teams"
    PAGERDUTY = "pagerduty", "PagerDuty"


class PagerDutySeverity(StrEnum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class PagerDutyRegion(StrEnum):
    US = "us"
    EU = "eu"


# What a PagerDuty destination that names neither gets, on every path that sends to one.
DEFAULT_PAGERDUTY_SEVERITY: Final = PagerDutySeverity.CRITICAL
DEFAULT_PAGERDUTY_REGION: Final = PagerDutyRegion.US


class IncidentAction(StrEnum):
    """What one event kind does to the incident an alert holds open in an incident manager."""

    TRIGGER = "trigger"
    RESOLVE = "resolve"


class AlertDestinationData(TypedDict):
    type: DestinationType
    slack_workspace_id: NotRequired[int]
    slack_channel_id: NotRequired[str]
    slack_channel_name: NotRequired[str]
    webhook_url: NotRequired[str]
    pagerduty_routing_key: NotRequired[str]
    pagerduty_severity: NotRequired[str]
    pagerduty_region: NotRequired[str]


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
    # Set only on the kinds that open or close an incident. An incident manager destination
    # subscribes to those kinds and no others; every other destination subscribes to the rest.
    incident_action: IncidentAction | None = None

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
    template: str | None = None  # "slack" | "discord" | "webhook" | "teams" | "pagerduty"
    status: str = "accepted"
    at: str  # ISO-8601 timestamp


class DestinationResolver(Protocol):
    """The lookup the product that owns destinations registers for native delivery."""

    def __call__(
        self, *, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
    ) -> list[AlertDestinationGroup]: ...


# Comparison against a source's own stack.
#
# What a comparison reads, and what a source must supply for one.
#
# A comparison joins one platform check to the check a source's own stack made of the same alert
# at the same due time. The platform side of that join is uniform: `legacy_configuration_id` on
# the configuration names the source's own row, and `evaluation_key` on the history row names the
# evaluation. The source side is not uniform. Logs keys its own checks on the window, insight will
# key on the scheduled run, and neither shape is reconstructible from the platform row alone. So a
# source supplies the correspondence through `SourceCorrespondence` rather than the harness
# guessing it.
#
# A source declares everything about itself on that one object: how to find its own verdicts, the
# two policies its stacks run, and which differences between them are deliberate. A second
# registration point in the shared package would let a source change one and not the other.
#
# Two stacks never evaluate at the same instant. The key is what corresponds; a timestamp is only
# a bound on how far apart two corresponding checks may sit.


@frozen
class CheckRef:
    """Addresses one platform check.

    `evaluation_key` is minted by the source and names the evaluation the check answered, so the
    pair survives a retry that recomputes the same check.
    """

    alert_id: UUID
    evaluation_key: str


@frozen
class PlatformCheck:
    """One row of the platform's check history, as a comparison reads it.

    A comparison is over `state`, not over `kind`, because a check that moved the alert while a
    cooldown or a mute held the notification back records `AlertEventKind.CHECK`. Counting kinds
    misses every suppressed move. `kind` and `previous_state` are carried so a report can say what
    the platform announced and what it moved from.

    `muted_notification` is the announcement a mute held back, as a `NotificationAction` value.
    It is the platform's only record that an alert was muted at the moment of a check, because a
    muted check that decided nothing holds nothing and leaves no other trace.
    """

    team_id: int
    configuration_id: UUID
    # None for a configuration no source backfilled, which nothing can be compared against.
    legacy_configuration_id: UUID | None
    alert_id: UUID
    grouping_key: str
    evaluation_key: str
    kind: str
    previous_state: str
    state: str
    muted_notification: str
    error_message: str
    occurred_at: datetime

    @property
    def ref(self) -> CheckRef:
        return CheckRef(alert_id=self.alert_id, evaluation_key=self.evaluation_key)


class SourceCoverage(StrEnum):
    """How far the source's own stack had got when the platform made this check.

    A source that cannot answer returns `UNKNOWN` rather than a guess, because a guess turns
    into a disagreement nobody can act on.
    """

    EVALUATED = "evaluated"
    SUPPRESSED = "suppressed"
    # The source's own stack had not reached this evaluation yet.
    BEHIND = "behind"
    UNKNOWN = "unknown"


class SuppressionReason(StrEnum):
    """Why a source's own stack made no check.

    `MUTED` covers a snooze and a schedule restriction together, because one platform policy flag
    covers both.
    """

    MUTED = "muted"
    DISABLED = "disabled"
    BROKEN = "broken"


@frozen
class SourceVerdict:
    """What a source's own stack held for the check that corresponds to one platform check.

    `state` is an `AlertState` value as `facade.lifecycle` spells it, which is the vocabulary the
    platform records. A source whose own tables spell its states differently translates here, at
    its own edge: insight stores the `posthog.schema_enums` spelling ("Firing", "Not firing"), and
    returning that raw would read as a disagreement on every check.
    """

    coverage: SourceCoverage
    state: str | None
    suppressed_by: SuppressionReason | None = None
    # When the source left `state`, so a report can date the state it is reporting.
    observed_at: datetime | None = None
    # When the source reached the state this check decided, which separates two cadences out of
    # phase from a real disagreement. The source answers it because it holds the check, and the
    # path there may take several transitions: not firing, errored, firing has reached firing.
    # Required, because None means the source never got there: a source that left it unset would
    # book every lag as a disagreement and nothing would fail.
    caught_up_at: datetime | None
    # Addresses the source's own row, so a person reading a disagreement can open both sides.
    evidence_id: str | None = None
    detail: str = ""


@frozen
class IntentionalDivergence:
    """One difference a source's platform stack makes on purpose.

    `recognizes` is what makes this a mechanism rather than a note: the classifier asks each
    declared divergence whether it explains the pair in front of it. A declaration without a
    working recognizer leaves its differences classified as real, which is the safe direction.

    `policy_flag` names the `AlertPolicy` field that causes it, and is what the ratchet matches
    against, so a source cannot configure a deliberate difference and leave it undeclared. Not
    every deliberate difference comes from a flag: insight collapses four failure kinds into two
    skip reasons, which no flag describes, so a declaration may leave it None and still be asked.

    The recognizer belongs to the source because the same flag shows up differently per source.
    Production logs stops checking a muted alert and its schedule stalls; insight keeps checking
    one and its schedule does not.
    """

    cause: str
    recognizes: Callable[[PlatformCheck, SourceVerdict], bool]
    why: str
    policy_flag: str | None = None


class SourceCorrespondence(Protocol):
    """How a source says which of its own history corresponds to a platform check.

    `verdicts_for` is batched rather than per check, because a source answers from its own tables
    and a per-check call would issue one query per row of a comparison window.

    A correspondence returns a verdict for every ref it was given. A check it cannot answer gets
    `SourceCoverage.UNKNOWN`, never a missing entry, so a caller cannot mistake silence for
    agreement.
    """

    source: SourceKind
    # What the source's own stack runs, against what its platform adapter runs. Declared here so
    # it stays next to the code that passes them to the machine.
    production_policy: AlertPolicy
    platform_policy: AlertPolicy
    intentional_divergences: tuple[IntentionalDivergence, ...]

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]: ...
