"""How a grouped check turns per-group observations into the groups an outcome reports.

A source measures each group and builds its machine snapshot. Everything after that is the same for
every source, so it lives here once: run the machine per group, leave out a new group that decided
nothing, put firing groups first, and admit what `max_instances` has room for.
"""

from collections.abc import Callable, Sequence
from dataclasses import field
from datetime import datetime

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import GroupOutcome, InstanceCheckState, PlatformAlertCheckInput
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    AlertCheckOutcome,
    AlertPolicy,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    decide_firing_episode,
    evaluate_alert_check,
)


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
) -> GroupDecision:
    """Each observed group run through the machine against its own instance.

    A new group that decided nothing is left out, so a quiet group costs no row. A source passes an
    observation for every open group it should judge, including one its query did not return.
    """
    existing = {instance.grouping_key for instance in check.instances}
    judged: list[tuple[GroupObservation, AlertSnapshot, AlertCheckOutcome]] = []
    for observation in observations:
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
                muted_notification=(
                    "" if outcome.muted_notification == NotificationAction.NONE else outcome.muted_notification.value
                ),
            ),
        )
        for observation, snapshot, outcome in judged
        if observation.grouping_key in admission.admitted
    )
    return GroupDecision(verdicts=verdicts, overflowed=admission.overflowed)
