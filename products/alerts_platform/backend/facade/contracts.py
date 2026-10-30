"""Contract types for alerts.

Framework-free types that describe what this product hands to its consumers and
accepts back. No Django, no DRF: other products read against these, and the Turbo
contract check watches this file to decide whether they must retest.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import asdict, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, NotRequired, Protocol, TypedDict
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

from products.alerts_platform.backend.facade.enums import DeliveryPath, PlatformAlertCheckStatus, PlatformAlertState

if TYPE_CHECKING:
    from pydantic import BaseModel

    # facade.lifecycle imports this module, so the policy type stays off the runtime import path.
    from products.alerts_platform.backend.facade.lifecycle import AlertPolicy


class SourceKind(StrEnum):
    LOGS = "logs"
    INSIGHT = "insight"
    BILLING = "billing"
    WAREHOUSE_SOURCE = "warehouse_source"
    WAREHOUSE_DESTINATION = "warehouse_destination"
    METRICS = "metrics"


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


class GroupingMode(LabeledStrEnum):
    SINGLE = "single", "Single"
    BY_RESULT_LABELS = "by_result_labels", "By result labels"


class OnOverflow(LabeledStrEnum):
    # The only mode, because a cap that drops groups silently reads the same as nothing being wrong.
    DEGRADE_VISIBLE = "degrade_visible", "Degrade visible"


DEFAULT_MAX_INSTANCES: Final = 100
# One check's outcome carries a group per instance, and it crosses Temporal whole, so
# `MAX_BATCH_PAYLOAD_BYTES` is sized to hold this many groups with their keys and labels at full length.
MAX_INSTANCES_CEILING: Final = 100
# The largest value a Postgres `integer` column holds, which bounds every stored count and duration.
MAX_STORED_INTEGER: Final = 2_147_483_647
# The most recent checks an N-of-M decision can look back over.
MAX_EVALUATION_PERIODS: Final = 10


@frozen
class Grouping:
    """How a configuration splits its results into instances.

    `keys` names the result labels whose values make a group's key, so it is empty for a single
    instance and required for grouping by labels. `max_instances` bounds how many instance rows a
    configuration holds, which bounds the messages one check can post.
    """

    mode: GroupingMode = GroupingMode.SINGLE
    keys: tuple[str, ...] = ()
    max_instances: int = DEFAULT_MAX_INSTANCES
    on_overflow: OnOverflow = OnOverflow.DEGRADE_VISIBLE

    def __post_init__(self) -> None:
        if self.mode == GroupingMode.SINGLE and self.keys:
            raise ValueError("a single-instance grouping takes no keys")
        if self.mode == GroupingMode.BY_RESULT_LABELS and not self.keys:
            raise ValueError("grouping by result labels needs at least one key")
        if len(set(self.keys)) != len(self.keys):
            raise ValueError("a grouping names each key once")
        if self.max_instances < 1:
            raise ValueError("max_instances must be at least 1")
        if self.max_instances > MAX_INSTANCES_CEILING:
            raise ValueError(f"max_instances must be at most {MAX_INSTANCES_CEILING}")

    @classmethod
    def from_stored(cls, stored: Mapping[str, Any]) -> Grouping:
        return cls(
            mode=GroupingMode(stored.get("mode", GroupingMode.SINGLE)),
            keys=tuple(stored.get("keys", ())),
            max_instances=int(stored.get("max_instances", DEFAULT_MAX_INSTANCES)),
            on_overflow=OnOverflow(stored.get("on_overflow", OnOverflow.DEGRADE_VISIBLE)),
        )

    def splits_like(self, other: Grouping) -> bool:
        """Whether the two key a check's results the same way, so their instances are interchangeable.

        `max_instances` and `on_overflow` are left out, because they bound how many groups are kept and
        change no group's key.
        """
        return (self.mode, self.keys) == (other.mode, other.keys)

    def to_stored(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "keys": list(self.keys),
            "max_instances": self.max_instances,
            "on_overflow": self.on_overflow.value,
        }


@frozen
class GroupAdmission:
    """Which of a check's groups the configuration has room for, which resting instances gave up
    their slot to make that room, and how many groups it turned away."""

    admitted: frozenset[str]
    overflowed: int
    evicted: frozenset[str] = frozenset()


@frozen
class InstanceCheckState:
    """One instance's runtime state, as the shared machine reads it for that group."""

    grouping_key: str
    state: str
    last_notified_at: datetime | None = None
    snooze_until: datetime | None = None
    firing_started_at: datetime | None = None
    last_seen_at: datetime | None = None

    def at_rest(self, now: datetime) -> bool:
        """Holds a slot and nothing else: not firing, failing or muted."""
        return self.state == PlatformAlertState.NOT_FIRING.value and (
            self.snooze_until is None or self.snooze_until <= now
        )

    @classmethod
    def composed(
        cls,
        *,
        grouping_key: str,
        state: str,
        check_status: str,
        configuration_snooze_until: datetime | None,
        snooze_until: datetime | None = None,
        last_notified_at: datetime | None = None,
        firing_started_at: datetime | None = None,
        last_seen_at: datetime | None = None,
    ) -> InstanceCheckState:
        """An instance as a check, history and the read API all see it.

        The machine reads ERRORED and BROKEN from the same field as firing, so a failing check status
        takes the place of the instance's state. A configuration mute extends every instance's, and
        the later of the two holds. The single definition, so what a check judges, what history
        records and what a reader sees cannot drift apart.
        """
        snoozes = [moment for moment in (configuration_snooze_until, snooze_until) if moment is not None]
        return cls(
            grouping_key=grouping_key,
            state=state if check_status == PlatformAlertCheckStatus.OK else check_status,
            last_notified_at=last_notified_at,
            snooze_until=max(snoozes, default=None),
            firing_started_at=firing_started_at,
            last_seen_at=last_seen_at,
        )


_NEVER_SEEN: Final = datetime.min.replace(tzinfo=UTC)


@frozen
class PlatformAlertCheckInput:
    """One configuration and its runtime state, as a source adapter reads it.

    `instances` holds every instance the configuration has, already composed with what belongs to
    the configuration: a failing check status replaces each state, and a configuration mute
    extends each snooze. A grouped source reads one per group it evaluates, and an open instance
    whose key a successful check does not return has gone and resolves.
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
    check_status: str
    snooze_until: datetime | None
    owned_by_platform: bool = False
    instances: tuple[InstanceCheckState, ...] = ()
    grouping: Grouping = field(default_factory=Grouping)
    # The calendar half of the schedule, so a source can tell when its own cadence has moved.
    recurrence_unit: str | None = None
    anchor_time: str | None = None

    @property
    def destination_alert_id(self) -> UUID:
        """The id the alert's destinations are matched on: the source row's for a copy, and the
        configuration's own for an alert whose source keeps no row."""
        return self.legacy_configuration_id or self.id

    def admit(self, grouping_keys: Sequence[str], *, now: datetime) -> GroupAdmission:
        """The groups a check may report, from keys in the source's priority order.

        A group that already has an instance is always admitted, so an open group can still
        resolve. New groups fill what `max_instances` leaves, front first. When that is not enough,
        a new group takes the slot of the least recently seen instance at rest, so resolved groups
        cannot lock a new breach out until they are reaped. An instance this check reports is
        never evicted, and only a group past every resting instance overflows.
        """
        keys = dict.fromkeys(grouping_keys)
        existing = {instance.grouping_key for instance in self.instances}
        held = len(existing)
        # An ungrouped configuration's one instance is its whole alert, so it never gives up its slot.
        victims = (
            []
            if self.grouping.mode == GroupingMode.SINGLE
            else sorted(
                (
                    instance
                    for instance in self.instances
                    if instance.grouping_key not in keys and instance.at_rest(now)
                ),
                key=lambda instance: (instance.last_seen_at or _NEVER_SEEN, instance.grouping_key),
            )
        )
        admitted: set[str] = set()
        evicted: set[str] = set()
        overflowed = 0
        for key in keys:
            if key in existing:
                admitted.add(key)
                continue
            # The write creates a row only below the cap. After the cap is lowered, one new group can
            # need several resting slots, and it takes none when there are not enough of them.
            needed = held + 1 - self.grouping.max_instances
            if needed > len(victims):
                overflowed += 1
                continue
            if needed > 0:
                evicted.update(victim.grouping_key for victim in victims[:needed])
                victims = victims[needed:]
                held -= needed
            admitted.add(key)
            held += 1
        return GroupAdmission(admitted=frozenset(admitted), overflowed=overflowed, evicted=frozenset(evicted))

    def instance(self, grouping_key: str = "") -> InstanceCheckState:
        """The instance for a group, or the state a group with no instance starts from."""
        for instance in self.instances:
            if instance.grouping_key == grouping_key:
                return instance
        return InstanceCheckState.composed(
            grouping_key=grouping_key,
            state=PlatformAlertState.NOT_FIRING.value,
            check_status=self.check_status,
            configuration_snooze_until=self.snooze_until,
        )

    def open_keys(self) -> list[str]:
        """The groups whose instance state is not NOT_FIRING. A check judges each one, returned or not."""
        return [
            instance.grouping_key
            for instance in self.instances
            if instance.state != PlatformAlertState.NOT_FIRING.value
        ]

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
    # Written only when the upsert creates the copy. An existing copy keeps the grouping its own
    # edits set, because a source row stores none.
    grouping: Grouping = Grouping()


@frozen
class PlatformOwnershipHandover:
    """A source alert handed to the platform, with the runtime state the platform carries on from."""

    legacy_configuration_id: UUID
    team_id: int
    state: PlatformAlertState
    last_notified_at: datetime | None
    consecutive_failures: int
    # The platform checks no earlier than a minute after the handover, whatever this says.
    next_check_at: datetime
    at: datetime


class HandbackRefusal(StrEnum):
    """Why the platform keeps an alert its source asked for back."""

    # The platform keys its incidents by episode, which the source's own stack cannot address, so a
    # firing alert stays until it resolves.
    FIRING = "firing"
    # A platform check may be running and could record or notify after the handback.
    CHECK_DUE = "check_due"
    # A handback carries one alert. Grouped alerts stay, and so does a calendar schedule its source
    # does not run.
    NOT_PORTABLE = "not_portable"


@frozen
class PlatformHandback:
    """The runtime state the source carries on from when the platform hands an alert back."""

    state: PlatformAlertState
    last_notified_at: datetime | None
    consecutive_failures: int
    next_check_at: datetime | None
    # False when the platform switched the copy off, such as for a configuration it cannot run.
    enabled: bool = True


@frozen
class PlatformAlertRuntime:
    """Where an alert the platform owns stands, and how it splits into instances, for a source whose
    API still shows the alert."""

    state: PlatformAlertState
    last_notified_at: datetime | None
    consecutive_failures: int
    next_check_at: datetime | None
    grouping: Grouping


@frozen
class PlatformStateChange:
    """One check that moved an alert the platform owns from one state to another."""

    occurred_at: datetime
    previous_state: PlatformAlertState
    state: PlatformAlertState


@frozen
class PlatformAlertHistory:
    """What the platform's check history says about an alert it owns, over one window.

    An alert the platform did not check in the window has no history at all, so a source can
    tell "not checked here" from "checked and succeeded".
    """

    state_changes: tuple[PlatformStateChange, ...]
    last_checked_at: datetime
    # None when the last check in the window succeeded.
    last_error_message: str | None


@frozen
class PlatformLastCheck:
    """The newest check of an alert the platform owns."""

    checked_at: datetime
    # None when the check measured nothing.
    value: float | None


@frozen
class PlatformCheckEntry:
    """One check of an alert the platform owns, as a source lists its checks."""

    occurred_at: datetime
    evaluation_key: str
    state: PlatformAlertState
    value: float | None
    # None when the check succeeded.
    error_message: str | None
    # What the source recorded beside the verdict. The platform reads only which keys it holds.
    source_detail: dict[str, Any] = field(default_factory=dict)


@frozen
class PlatformCheckPage:
    """A page of an alert's checks, newest first, and how many checks the window holds."""

    total: int
    checks: tuple[PlatformCheckEntry, ...]


@frozen
class PlatformCheckEvent:
    """One check of an alert the platform owns that moved its state or failed."""

    occurred_at: datetime
    evaluation_key: str
    previous_state: PlatformAlertState
    state: PlatformAlertState
    value: float | None
    condition: dict[str, Any]
    query_duration_ms: int | None
    error_message: str | None


@frozen
class PlatformCheckEventPage:
    """The newest checks of an alert that moved its state or failed, and how many there are in all."""

    events: tuple[PlatformCheckEvent, ...]
    total: int


class SkipReason(StrEnum):
    """Why a check reached an outcome without a query answering it.

    A label on the platform's own counters. It never reaches an alert's state or schedule. A check
    that was evaluated has no skip reason, which is `None` rather than a member here.
    """

    BROKEN_CONFIG = "broken_config"
    QUERY_FAILED = "query_failed"
    # The source's own stack runs no query for this check, so the source does not either: a
    # snooze or a schedule restriction where that stack gates evaluation, or data not ready yet.
    SOURCE_RULE = "source_rule"
    # ClickHouse refused the query for load, not because of the alert. The check leaves the alert's
    # state alone, so a comparison can set it aside instead of reading load as a disagreement.
    CAPACITY = "capacity"


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
class GroupOutcome:
    """What one check decided for one group. The platform turns each into an instance write and a
    history row.

    A source that does not group sends one of these with the empty key, which is its one instance.
    """

    grouping_key: str
    kind: AlertEventKind
    new_state: str
    notified: bool
    firing_episode: FiringEpisode | None = None
    value: float | None = None
    labels: dict[str, str] = field(default_factory=dict)
    # What a mute held back, so history separates a muted fire from a check that said nothing.
    muted_notification: str = ""
    # What the source's own stack sent beside this verdict, which the platform stores and returns
    # without reading, so a delivery on the HogFunction path can send what the source sent.
    source_detail: dict[str, Any] = field(default_factory=dict)


@frozen
class CheckFailure:
    """What the shared machine decided for a check that could not evaluate.

    It belongs to the check, not to a group, because a failed query returns no groups to attribute
    the failure to. `new_state` is the machine's verdict, which stays the prior state under a
    policy that rides through errors and becomes ERRORED or BROKEN under one that does not.
    """

    kind: AlertEventKind
    new_state: str
    notified: bool
    firing_episode: FiringEpisode | None = None
    muted_notification: str = ""
    # As on `GroupOutcome`: what the source's stack sends beside the failure, stored unread.
    source_detail: dict[str, Any] = field(default_factory=dict)


@frozen
class PlatformAlertOutcome:
    """What one check decided. The platform turns this into rows.

    Every check produces one, including a check a source skipped. A skip that records nothing
    leaves its due time where it was, so discovery finds the same work every tick.

    The fields here describe the check, and each of `groups` describes one group's verdict. A failed
    query fails every group at once, so the failure count, `disable` and `failure` belong to the
    check, and a failed check carries no groups. A successful check of an ungrouped source carries
    exactly one group with the empty key; a grouped source's may carry none when nothing is open.
    """

    configuration_id: UUID
    evaluation_key: str
    consecutive_failures: int
    groups: tuple[GroupOutcome, ...] = ()
    failure: CheckFailure | None = None
    skipped: bool = False
    # New groups `max_instances` had no room for, which the delivery names so a cap is never silent.
    overflowed: int = 0
    # The source cut its results before admission, so `overflowed` counts only the groups it saw.
    overflow_is_lower_bound: bool = False
    # Resting instances whose slot a new group took. The write deletes them before it creates rows.
    evicted: tuple[str, ...] = ()
    error_message: str | None = None
    query_duration_ms: int | None = None
    # Recording an outcome without it leaves a configuration discovery keeps handing back to an
    # evaluation that cannot succeed.
    disable: bool = False
    # A team's checks with the same group are due in one slot, so a source that answers them with
    # one query can do so. None spreads the configuration by its own id.
    schedule_group: str | None = None
    # The id the source's own stack times this configuration's checks by. The platform then checks
    # at the minute that stack does, because a metric read at another minute can breach where the
    # source's own check does not. None times the checks by the configuration's own id.
    schedule_key: str | None = None
    # The grouping the check ran under. An edit can change it while the check is in flight, and the
    # groups of a stale check are keyed for a grouping the configuration no longer has, so they are
    # dropped. None when the outcome carries no groups to drop.
    grouping: Grouping | None = None
    # The delivery this check decided on, held back until its source or the safety net releases it.
    # The source leaves it out of the deliveries it starts.
    held_delivery: HeldDelivery | None = None

    @classmethod
    def ungrouped(
        cls,
        *,
        configuration_id: UUID,
        evaluation_key: str,
        consecutive_failures: int,
        kind: AlertEventKind,
        new_state: str,
        notified: bool,
        failed: bool,
        firing_episode: FiringEpisode | None = None,
        value: float | None = None,
        muted_notification: str = "",
        error_message: str | None = None,
        query_duration_ms: int | None = None,
        disable: bool = False,
        skipped: bool = False,
        schedule_group: str | None = None,
        source_detail: dict[str, Any] | None = None,
    ) -> PlatformAlertOutcome:
        """A check of a source that does not group: its one verdict on the empty key, or its failure."""
        failure = (
            CheckFailure(
                kind=kind,
                new_state=new_state,
                notified=notified,
                firing_episode=firing_episode,
                muted_notification=muted_notification,
                source_detail=source_detail or {},
            )
            if failed
            else None
        )
        groups = (
            ()
            if failed
            else (
                GroupOutcome(
                    grouping_key="",
                    kind=kind,
                    new_state=new_state,
                    notified=notified,
                    firing_episode=firing_episode,
                    value=value,
                    muted_notification=muted_notification,
                    source_detail=source_detail or {},
                ),
            )
        )
        return cls(
            configuration_id=configuration_id,
            evaluation_key=evaluation_key,
            consecutive_failures=consecutive_failures,
            groups=groups,
            grouping=Grouping(),
            failure=failure,
            error_message=error_message,
            query_duration_ms=query_duration_ms,
            disable=disable,
            skipped=skipped,
            schedule_group=schedule_group,
        )

    def __post_init__(self) -> None:
        if self.failure is not None and self.groups:
            raise ValueError("a failed check reports no groups")
        keys = [group.grouping_key for group in self.groups]
        if len(set(keys)) != len(keys):
            raise ValueError("an outcome names each group once")
        if set(self.evicted) & set(keys):
            raise ValueError("an outcome cannot evict a group it reports")
        held = self.held_delivery
        if held is not None and (
            held.request.configuration_id != str(self.configuration_id)
            or held.request.evaluation_key != self.evaluation_key
        ):
            raise ValueError("an outcome can only hold its own delivery")


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
    # The evaluation this transition came from, so a source can read back what it put in the key.
    evaluation_key: str = ""
    source_detail: dict[str, Any] = field(default_factory=dict)


@frozen
class EvaluationAnnouncement:
    """What one evaluation left for a destination to say.

    One transition is one message. A level between this and the transitions would be the place a
    fan-in policy lived, and fan-in was deprioritized on 2026-09-28, so there is nothing for it
    to hold. It arrives with fan-in rather than waiting here empty.
    """

    configuration_id: str
    source: SourceKind
    alert_name: str
    # Evaluation-level, so it sits here rather than on a transition: a failed check fails the
    # whole evaluation, and every group in one announcement saw the same count.
    consecutive_failures: int
    transitions: tuple[AnnouncedTransition, ...]
    # Groups the configuration had no room for. The first message names them, so a cap never drops
    # a group without anyone being told.
    overflowed: int = 0
    overflow_is_lower_bound: bool = False


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

    `owned_by_platform` is the owner when the check was read, not when the delivery runs. The
    source decided its own send for that check from the same owner, so a retry across a cutover
    or a rollback still has exactly one stack sending.
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
    # The alert's page in the source's own product. Without one a message links to the platform's page.
    source_alert_url: str | None = None
    owned_by_platform: bool = False
    overflowed: int = 0
    overflow_is_lower_bound: bool = False
    # How many activities the delivery workflow splits an evaluation into, by `MAX_TRANSITIONS_PER_DELIVERY`,
    # and which of them one activity sends. The workflow sets `part`.
    parts: int = 1
    part: int = 0

    def to_stored(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_stored(cls, stored: Mapping[str, Any]) -> AlertDeliveryRequest:
        # The converter Temporal decodes this type with, so the stored form loads the way the wire form does.
        import temporalio.converter  # noqa: PLC0415 — keeps temporalio off django.setup(), which loads this via the models

        return temporalio.converter.value_to_type(cls, dict(stored))


MAX_HOLD_REASON_LENGTH: Final = 64


@frozen
class HeldDelivery:
    """A delivery a check decided on and held back until something releases it.

    The source releases it with a verdict, or with the request's send when it cannot run what it
    held for. The platform's safety net sends it once `release_after_seconds` have passed since the
    check was recorded, so a release that never comes still delivers.
    """

    request: AlertDeliveryRequest
    # Why it is held, which the platform stores and does not read.
    reason: str
    release_after_seconds: int

    def __post_init__(self) -> None:
        # Rejected here rather than by the hold's column, where it would roll back the whole batch's record.
        if len(self.reason) > MAX_HOLD_REASON_LENGTH:
            raise ValueError(f"a hold reason is at most {MAX_HOLD_REASON_LENGTH} characters")
        if self.release_after_seconds < 0:
            raise ValueError("a hold cannot release before it is recorded")


@frozen
class HeldDeliveryAddress:
    """The one hold an evaluation of a configuration can have."""

    team_id: int
    configuration_id: str
    evaluation_key: str


@frozen
class SourceBatchEvaluation:
    """What one batch decided, before any of it is written.

    Evaluation returns this and the write runs as its own activity, so Temporal has the
    deliveries in history before anything can advance a schedule past them.
    """

    outcomes: tuple[PlatformAlertOutcome, ...]
    deliveries: tuple[AlertDeliveryRequest, ...]
    # Pairs the payload bound or a full evaluation pool left out. They keep their due time and a
    # later tick re-evaluates them, the way a truncated cohort already behaves.
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
    owner: str
    check_status: str


@frozen
class PlatformAlertSnapshot:
    """One instance's runtime state, for a reader outside this product."""

    id: UUID
    grouping_key: str
    state: str
    firing_started_at: datetime | None
    last_notified_at: datetime | None
    snooze_until: datetime | None
    labels: dict[str, str] = field(default_factory=dict)


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
    grouping: Grouping
    snooze_until: datetime | None
    check_status: str
    overflowed_groups: int
    overflow_is_lower_bound: bool
    owner: str
    created_at: datetime
    updated_at: datetime
    alerts: tuple[PlatformAlertSnapshot, ...]
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    @property
    def destination_alert_id(self) -> UUID:
        """The id the alert's destinations are matched on: the source row's for a copy, and the
        configuration's own for an alert whose source keeps no row."""
        return self.legacy_configuration_id or self.id


@frozen
class PlatformAlertConfigurationEdit:
    """The settings of a configuration that its owner may change through the API.

    The schedule, the source kind and every runtime field stay out, because a write that could set
    them would read as drift on the next check.
    """

    name: str
    enabled: bool
    source_config: dict[str, Any]
    grouping: Grouping
    schedule_restriction: dict[str, Any] | None
    evaluation_periods: int
    datapoints_to_alarm: int
    cooldown_minutes: int
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)


class InvalidPlatformAlertEdit(ValueError):
    """An edit the configuration's source kind rejects, naming the field at fault."""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field_name = field_name


class PlatformAlertNotEditable(Exception):
    """A configuration the platform does not own, so its source's own API writes it."""


class UnknownPlatformAlertGroup(LookupError):
    """A grouping key the configuration has no instance for."""


class SourceEditMirror(Protocol):
    """Writes an edit made through the platform API onto the source's own row.

    While a source keeps its own row for an alert the platform owns, the two must agree: the
    source's API reads that row, and a rollback hands it back. It runs before the platform locks
    its copy, because every other writer of both rows takes the source's row first. It locks the
    source's row and returns the writer for the edit, or None when the row is gone. It raises
    `PlatformAlertNotEditable` when the source's row belongs to another team than the copy, because
    the platform API checked access to the copy's team only.
    """

    def __call__(
        self, *, team_id: int, legacy_configuration_id: UUID
    ) -> Callable[[PlatformAlertConfigurationEdit], None] | None: ...


class PlatformAlertCreateRefused(Exception):
    """A create the source refuses as a whole, such as one past its per-team limit."""


class SourceCreate(Protocol):
    """Creates an alert through the platform API on a source that keeps its own row for it.

    Runs in the create's transaction. It writes the source's row and the platform's copy, both owned
    by the platform, the way the source hands over an alert it created itself, and returns the id of
    the source's row. The copy carries that id as `legacy_configuration_id`. It raises
    `PlatformAlertCreateRefused` when the source refuses the create.
    """

    def __call__(self, *, team_id: int, edit: PlatformAlertConfigurationEdit, created_by_id: int | None) -> UUID: ...


class SourceDelete(Protocol):
    """Deletes an alert the platform owns through the platform API, on a source that keeps its own row.

    It removes the source's row and the platform's copy, and closes the alert's open incidents
    before either goes, while the destinations the resolves go to still exist. So it runs outside
    any transaction. It raises `PlatformAlertNotEditable` when the source's row belongs to another
    team than the copy, because the platform API checked access to the copy's team only.
    """

    def __call__(self, *, team_id: int, legacy_configuration_id: UUID) -> None: ...


class SourceConfigTeamCheck(Protocol):
    """Checks a `source_config` against the project it is written in, which `validate` cannot see.

    For example, that its ids name rows of that project. It raises `InvalidPlatformAlertEdit`.
    """

    def __call__(self, *, team_id: int, edit: PlatformAlertConfigurationEdit) -> None: ...


class NativeAlertRemoveDestinations(Protocol):
    """Removes the destinations of an alert that is about to be deleted.

    The alert's open incidents are closed before this runs, while the destinations their resolves go
    to still exist. It runs in the delete's transaction, so a delete that fails keeps them.
    """

    def __call__(self, *, team_id: int, configuration_id: UUID) -> None: ...


@frozen
class NativeAlertLifecycle:
    """How the platform creates and deletes alerts of a kind whose source keeps no row for them.

    The configuration is the alert's only record, and its own id is the id the alert's destinations
    are matched on.
    """

    check_interval_minutes: int
    # Removes the source's HogFunction destinations of a deleted alert. None for a kind whose
    # destinations are `AlertDestination` rows from the start, which go with the configuration.
    remove_destinations: NativeAlertRemoveDestinations | None = None

    @property
    def platform_destinations(self) -> bool:
        return self.remove_destinations is None


@frozen
class SourceConfigSpec:
    """A source kind's schema for `source_config` and its rules for a whole edit.

    `model` validates `source_config`. `validate` raises `InvalidPlatformAlertEdit` for a rule that
    spans fields, such as one that reads `enabled`. `check_in_team` runs when a create or an edit
    sets `source_config`. `mirror` runs in the edit's transaction. Without
    `create` or `delete`, the API cannot create or delete alerts of the kind, unless the kind is
    `native`: then the platform creates and deletes them itself, and the source keeps no row.
    """

    model: type[BaseModel]
    validate: Callable[[PlatformAlertConfigurationEdit], None]
    check_in_team: SourceConfigTeamCheck | None = None
    mirror: SourceEditMirror | None = None
    create: SourceCreate | None = None
    delete: SourceDelete | None = None
    # Where the source's incident destinations listen for a close, and the alert's page in the
    # source's product. A control-plane close needs both to address its resolve.
    incident_event_ids: Mapping[str, str] | None = None
    alert_url: Callable[[int, UUID], str] | None = None
    native: NativeAlertLifecycle | None = None
    # A PostHog feature flag a project needs, beside `platform-alerts`, to create alerts of this kind.
    # A new kind names its own flag, so it opens on its own schedule while the others stay generally
    # available.
    rollout_flag: str | None = None

    def __post_init__(self) -> None:
        # The source-row hooks write a row a native kind does not have.
        if self.native is not None and (self.mirror or self.create or self.delete):
            raise ValueError("A native kind keeps no source row, so it cannot register mirror, create or delete.")

    @property
    def creatable(self) -> bool:
        return self.native is not None or self.create is not None


SourceConfigLoader = Callable[[], SourceConfigSpec]


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
    EMAIL = "email", "Email"
    IN_APP = "in_app", "In-app notification"


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
    # Request headers a user added to a webhook, such as an auth token, as sorted (name, value)
    # pairs so a destination stays hashable. Secret-bearing, so never shown in a read response.
    webhook_headers: NotRequired[dict[str, str]]
    pagerduty_routing_key: NotRequired[str]
    pagerduty_severity: NotRequired[str]
    pagerduty_region: NotRequired[str]
    email_addresses: NotRequired[list[str]]
    in_app_user_ids: NotRequired[list[int]]
    # What an in-app notification is about, so the inbox applies its access rules for that resource.
    in_app_resource_type: NotRequired[str]
    in_app_resource_id: NotRequired[str]
    # A path in the app, because the inbox opens it with the client-side router.
    in_app_url: NotRequired[str]


# The transitions a destination can send about. `CHECK` announces nothing, so no destination hears it.
DESTINATION_EVENT_KINDS: Final = frozenset(
    {AlertEventKind.FIRING, AlertEventKind.RESOLVED, AlertEventKind.ERRORED, AlertEventKind.BROKEN}
)


@frozen
class NewAlertDestination:
    """One destination to add to an alert the platform owns the destinations of."""

    data: AlertDestinationData
    event_kinds: tuple[AlertEventKind, ...]
    enabled: bool = True
    legacy_hog_function_ids: tuple[UUID, ...] = ()


@frozen
class StoredAlertDestination:
    """One `AlertDestination` row, with its configuration decrypted."""

    id: UUID
    configuration_id: UUID
    data: AlertDestinationData
    event_kinds: tuple[AlertEventKind, ...]
    enabled: bool
    consecutive_failures: int
    legacy_hog_function_ids: tuple[UUID, ...]


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
    """One destination an alert delivers to: the HogFunctions a person configured, or a destination
    with none, such as an insight alert's subscriber email."""

    hog_function_ids: tuple[UUID, ...]
    data: AlertDestinationData
    fully_enabled: bool

    @property
    def receives_emitted_events(self) -> bool:
        """Whether the source's emitted internal events reach it. Only a HogFunction listens to them."""
        return bool(self.hog_function_ids)


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


@frozen
class MessageDetail:
    """One labelled fact in a message. Every provider renders these the same way, as a Slack
    section, an Adaptive Card body, or lines of markdown."""

    label: str
    value: str


@frozen
class MessageLink:
    label: str
    url: str


@frozen
class MessageImage:
    url: str
    alt_text: str


@frozen
class SourceDescription:
    """What a source says about one transition, in the words its own product uses.

    The platform imports no source, so it can say only "Value: 11". A source can say "11 logs in
    10m". Every part is optional, and a part a source leaves out falls back to the platform's
    own wording or to nothing.
    """

    # Replaces the platform's breach details. A failed or turned-off check keeps the platform's
    # failure details, because the failure is the platform's, not the source's.
    details: tuple[MessageDetail, ...] = ()
    # Short lines of small print, such as which services an alert watches.
    context: tuple[str, ...] = ()
    # Where the data behind the alert is, such as the matching logs.
    data_link: MessageLink | None = None
    # Slack elements that act on the alert from the message, such as a snooze menu, beside the
    # buttons. They are Slack's own Block Kit, so every other provider leaves them out.
    slack_elements: tuple[dict[str, Any], ...] = ()


class SourceDescriber(Protocol):
    """How a source describes its transitions. A source registers one for native delivery.

    It runs once per destination on the send path, inside a delivery that a held thread or a
    failure repeats. So it builds its answer from the transition alone and does no I/O.
    """

    def __call__(self, *, project_id: int, transition: AnnouncedTransition) -> SourceDescription: ...


class SourceRecipients(Protocol):
    """Who a source's own settings say to email about an alert, beside the destinations a person added.

    It runs once per delivery of an alert whose destinations the platform owns.
    """

    def __call__(self, *, team_id: int, configuration_id: UUID) -> list[str]: ...


@frozen
class SlackMessageContent:
    text: str
    blocks: list[dict[str, Any]]
    attachments: list[dict[str, Any]] = field(default_factory=list)


class SourceSlackRenderer(Protocol):
    """A source's own Slack layout for a transition, or None to use the platform's.

    Runs on the send path, so it reads only the transition it is given. The platform catches a
    renderer that raises and sends its own layout instead, so a broken renderer costs the card
    rather than the notification.

    `text` is what a push notification and a screen reader read, so it is never empty, whether or
    not the card itself lives in `attachments`. The platform adds the group-limit warning to the
    content wherever it finds room, and adds the state line to it on a later edit; neither assumes
    a particular block order.
    """

    def __call__(
        self,
        *,
        team_id: int,
        transition: AnnouncedTransition,
        alert_name: str,
        alert_url: str,
        project: MessageLink | None,
        image: MessageImage | None,
    ) -> SlackMessageContent | None: ...


class SourceImageResolver(Protocol):
    """The picture a message shows for a transition, such as an insight's chart, or None.

    Runs on the send path like a describer, but it may read storage: a picture's URL can open it
    without a login, so the source stores the picture by id and mints the URL as the message goes.
    A provider that cannot show a picture leaves it out.
    """

    def __call__(self, *, team_id: int, transition: AnnouncedTransition) -> MessageImage | None: ...


class LegacyWebhookBody(Protocol):
    """The webhook body a source's own stack sent, for teams whose receivers still parse it.

    Runs on the send path like a describer, so it builds the body from its arguments and does no
    I/O. `alert_id` is the id the source's destinations match on.
    """

    def __call__(
        self,
        *,
        project_id: int,
        alert_id: str,
        alert_name: str,
        consecutive_failures: int,
        transition: AnnouncedTransition,
    ) -> dict[str, Any]: ...


class DeliveryPathChooser(Protocol):
    """Which path an alert's destinations allow now. The product that owns destinations registers it.

    Answers `HOG_FUNCTION` whenever it is unsure, because that path sends what the source's own
    stack sent. It reads destinations and flags, so it runs once per delivery, not per destination.
    """

    def __call__(
        self, *, source: SourceKind, team_id: int, alert_id: str, allowed_event_ids: Collection[str]
    ) -> DeliveryPath: ...


@frozen
class LegacyEventEmission:
    """One transition the platform hands to its source on the HogFunction path."""

    transition: AnnouncedTransition
    # The source emits the transition's message event, as its own stack did when it notified.
    sends_message: bool
    # The source emits the incident event for this action too, when it is set.
    incident_action: IncidentAction | None

    @property
    def event_count(self) -> int:
        return int(self.sends_message) + int(self.incident_action is not None)


class LegacyEventEmitter(Protocol):
    """Emits the internal events a source's own stack emitted, for transitions on the HogFunction path.

    Returns only once the broker has every event, and raises otherwise, so delivery can retry. A
    retry emits the events again, so each event carries an id stable across attempts that a
    receiver can deduplicate on. The source's destinations match on `request.destination_alert_id`.
    """

    def __call__(
        self,
        *,
        request: AlertDeliveryRequest,
        announcement: EvaluationAnnouncement,
        emissions: Sequence[LegacyEventEmission],
    ) -> None: ...


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
    key survives a retry that recomputes the same check. The configuration tells apart failed
    checks of different configurations, which all carry the nil `alert_id`.
    """

    configuration_id: UUID
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
        return CheckRef(
            configuration_id=self.configuration_id, alert_id=self.alert_id, evaluation_key=self.evaluation_key
        )


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


@frozen
class DestinationSend:
    """One message sent to one destination, on either delivery path, with how it went.

    `destination_id` is the HogFunction the send was for, which names its event kind.
    `error` is set only for a failed native send. A HogFunction failure has none, because its log
    lines can quote credential-bearing inputs.
    """

    destination_id: str
    sent_at: datetime
    path: DeliveryPath
    succeeded: bool
    error: str | None
