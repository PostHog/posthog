"""How a grouped check turns per-group observations into the groups an outcome reports.

A source measures each group and builds its machine snapshot. Everything after that is the same for
every source, so it lives here once: run the machine per group, leave out a new group that decided
nothing, put firing groups first, and admit what `max_instances` has room for.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import field
from datetime import datetime
from typing import Final
from uuid import UUID

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    GroupOutcome,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
)
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    AlertCheckOutcome,
    AlertPolicy,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    Outcome,
    decide_firing_episode,
    evaluate_alert_check,
)

# `PlatformAlert.grouping_key` holds at most this many characters, so a longer key is hashed.
MAX_GROUPING_KEY_LENGTH: Final = 255
_HASHED_PREFIX: Final = "sha256:"


def bounded_grouping_key(key: str) -> str:
    """A key that fits the column. Stable across checks, so a group keeps its row."""
    if len(key) <= MAX_GROUPING_KEY_LENGTH:
        return key
    return f"{_HASHED_PREFIX}{hashlib.sha256(key.encode()).hexdigest()}"


def is_hashed_grouping_key(key: str) -> bool:
    """Whether `bounded_grouping_key` hashed this key, so the value it came from is gone."""
    return key.startswith(_HASHED_PREFIX)


@frozen
class GroupObservation:
    """What a source measured for one group. `prior_breached` is newest first, as the machine reads it."""

    grouping_key: str
    current_breached: bool
    prior_breached: tuple[bool, ...] = ()
    value: float | None = None
    labels: dict[str, str] = field(default_factory=dict)


@frozen
class GroupVerdict:
    observation: GroupObservation
    snapshot: AlertSnapshot
    outcome: AlertCheckOutcome
    group: GroupOutcome


@frozen
class GroupDecision:
    """The admitted groups, firing first, and how many new groups the cap turned away."""

    verdicts: tuple[GroupVerdict, ...]
    overflowed: int

    def as_outcome(
        self, *, configuration_id: UUID, evaluation_key: str, query_duration_ms: int | None
    ) -> PlatformAlertOutcome:
        """The outcome of a grouped check that ran. A query that ran reset the failure count."""
        return PlatformAlertOutcome(
            configuration_id=configuration_id,
            evaluation_key=evaluation_key,
            consecutive_failures=0,
            groups=tuple(verdict.group for verdict in self.verdicts),
            query_duration_ms=query_duration_ms,
            overflowed=self.overflowed,
        )


def muted_value(outcome: Outcome) -> str:
    """The stored form of what a mute held back: empty when nothing was held."""
    muted = getattr(outcome, "muted_notification", NotificationAction.NONE)
    return "" if muted == NotificationAction.NONE else muted.value


def _not_breaching(grouping_key: str) -> GroupObservation:
    return GroupObservation(grouping_key=grouping_key, current_breached=False)


def _decided_nothing(outcome: AlertCheckOutcome) -> bool:
    return (
        outcome.new_state == AlertState.NOT_FIRING
        and outcome.notification == NotificationAction.NONE
        and outcome.muted_notification == NotificationAction.NONE
    )


def decide_groups(
    check: PlatformAlertCheckInput,
    observations: Sequence[GroupObservation],
    *,
    snapshot_of: Callable[[InstanceCheckState, tuple[bool, ...]], AlertSnapshot],
    policy: AlertPolicy,
    now: datetime,
    muted: bool = False,
    absent: Callable[[str], GroupObservation | None] = _not_breaching,
) -> GroupDecision:
    """Each observed group run through the machine against its own instance.

    A new group that decided nothing is left out, so a quiet group costs no row. An open group the
    check did not return is judged through `absent`, as not breaching unless a source says what it
    measured, so a group that vanished resolves. `absent` returns None for a group the source cannot
    judge from its absence.
    """
    existing = {instance.grouping_key for instance in check.instances}
    # One observation per key. Two results can share a label, and a breaching one must not be lost.
    by_key: dict[str, GroupObservation] = {}
    for observation in observations:
        kept = by_key.get(observation.grouping_key)
        if kept is None or (observation.current_breached and not kept.current_breached):
            by_key[observation.grouping_key] = observation
    for key in check.open_keys():
        if key not in by_key and (missing := absent(key)) is not None:
            by_key[key] = missing
    judged: list[tuple[GroupObservation, AlertSnapshot, AlertCheckOutcome]] = []
    for observation in by_key.values():
        snapshot = snapshot_of(check.instance(observation.grouping_key), observation.prior_breached)
        outcome = evaluate_alert_check(
            snapshot, CheckInput(threshold_breached=observation.current_breached, muted=muted), now, policy=policy
        )
        if observation.grouping_key not in existing and _decided_nothing(outcome):
            continue
        judged.append((observation, snapshot, outcome))

    # Firing groups first, so a cap keeps the groups that announce something.
    judged.sort(key=lambda item: item[2].new_state == AlertState.NOT_FIRING)
    admission = check.admit([observation.grouping_key for observation, _, _ in judged])
    verdicts = tuple(
        GroupVerdict(
            observation=observation,
            snapshot=snapshot,
            outcome=outcome,
            group=GroupOutcome(
                grouping_key=observation.grouping_key,
                kind=NOTIFICATION_EVENT_KINDS[outcome.notification],
                new_state=outcome.new_state.value,
                notified=outcome.update_last_notified_at,
                firing_episode=decide_firing_episode(snapshot, outcome, now, policy=policy),
                value=observation.value,
                labels=observation.labels,
                muted_notification=muted_value(outcome),
            ),
        )
        for observation, snapshot, outcome in judged
        if observation.grouping_key in admission.admitted
    )
    return GroupDecision(verdicts=verdicts, overflowed=admission.overflowed)
