"""How a grouped check turns per-group observations into the groups an outcome reports.

A source measures each group and builds its machine snapshot. Everything after that is the same for
every source, so it lives here once: run the machine per group, leave out a new group that decided
nothing, put firing groups first, and admit what `max_instances` has room for.
"""

import re
import json
import math
import hashlib
from collections.abc import Callable, Collection, Sequence
from dataclasses import field
from datetime import datetime
from typing import Final
from uuid import UUID

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    Grouping,
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


def is_hashed_grouping_key(key: str) -> bool:
    """Whether `bounded_grouping_key` hashed this key, so the value it came from is gone."""
    return key.startswith(_HASHED_PREFIX)


# PostgreSQL text and JSONB reject NUL, and UTF-8 cannot encode a surrogate. Either one aborts the
# transaction that records the whole batch.
_UNSTORABLE: Final = re.compile("[\x00\ud800-\udfff]")


def bounded_grouping_key(key: str) -> str:
    """A key the column can store. Stable across checks, so a group keeps its row.

    A key stays as it is only when it fits, PostgreSQL can store it, and it cannot read as a hash.
    Every other key is hashed. A literal key in the hash namespace is hashed too, because otherwise
    it would share a row with the long key whose digest it spells.
    """
    if len(key) <= MAX_GROUPING_KEY_LENGTH and not is_hashed_grouping_key(key) and not _UNSTORABLE.search(key):
        return key
    return f"{_HASHED_PREFIX}{hashlib.sha256(key.encode('utf-8', 'surrogatepass')).hexdigest()}"


# A label value can come from ingested data, such as a service name, so its size is the sender's
# choice. Every group's labels cross Temporal on the outcome, and a cap on the count and on each
# encoded size keeps a check's outcome inside `MAX_BATCH_PAYLOAD_BYTES` at `MAX_INSTANCES_CEILING`.
MAX_GROUP_LABELS: Final = 4
# In bytes of the JSON a payload carries, where a non-ASCII character is escaped to up to 12 bytes.
MAX_LABEL_BYTES: Final = 256
_TRUNCATED: Final = "…"


def _bounded_label(value: str) -> str:
    # A label is display only, so a character the database cannot store shows as a replacement.
    value = _UNSTORABLE.sub("\ufffd", value)
    if _encoded_length(value) <= MAX_LABEL_BYTES:
        return value
    budget = MAX_LABEL_BYTES - _encoded_length(_TRUNCATED)
    kept: list[str] = []
    for char in value:
        budget -= _encoded_length(char)
        if budget < 0:
            break
        kept.append(char)
    return "".join(kept) + _TRUNCATED


def _encoded_length(value: str) -> int:
    return len(json.dumps(value)) - 2


def bounded_labels(labels: dict[str, str]) -> dict[str, str]:
    """The labels a group may carry: the first `MAX_GROUP_LABELS`, each name and value storable and cut to size.

    Display only. The grouping key is derived from the full values, so a cut label never merges two groups.
    """
    return {_bounded_label(name): _bounded_label(value) for name, value in list(labels.items())[:MAX_GROUP_LABELS]}


# One delivery activity sends every message it holds, to every destination, inside its timeout. An
# evaluation with more transitions than this is split into parts that each retry on their own.
MAX_TRANSITIONS_PER_DELIVERY: Final = 5


def delivery_parts(outcome: PlatformAlertOutcome, incident_grouping_keys: Collection[str] = ()) -> int:
    """How many delivery activities an outcome's transitions need.

    Counts the rows the delivery reads back: every group that announced, every group whose firing
    opened or closed, and a failure.
    """
    transitions = sum(
        1
        for group in outcome.groups
        if group.kind != AlertEventKind.CHECK or group.grouping_key in incident_grouping_keys
    )
    if outcome.failure is not None and outcome.failure.kind != AlertEventKind.CHECK:
        transitions += 1
    return parts_for(transitions)


def parts_for(transitions: int) -> int:
    """How many delivery activities this many transitions need."""
    return max(1, math.ceil(transitions / MAX_TRANSITIONS_PER_DELIVERY))


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
    """The admitted groups, firing first, the resting instances evicted to admit them, and how many
    new groups the cap turned away."""

    verdicts: tuple[GroupVerdict, ...]
    overflowed: int
    evicted: frozenset[str] = frozenset()

    def as_outcome(
        self,
        *,
        configuration_id: UUID,
        evaluation_key: str,
        grouping: Grouping,
        query_duration_ms: int | None,
        results_cut: bool,
    ) -> PlatformAlertOutcome:
        """The outcome of a grouped check that ran. A query that ran reset the failure count.

        `results_cut` says the source dropped results before they were observed. Groups it dropped
        may also have been turned away, so a non-zero overflow is then only a lower bound.
        """
        return PlatformAlertOutcome(
            configuration_id=configuration_id,
            evaluation_key=evaluation_key,
            consecutive_failures=0,
            groups=tuple(verdict.group for verdict in self.verdicts),
            grouping=grouping,
            query_duration_ms=query_duration_ms,
            overflowed=self.overflowed,
            overflow_is_lower_bound=results_cut and self.overflowed > 0,
            evicted=tuple(sorted(self.evicted)),
        )


def muted_value(outcome: Outcome) -> str:
    """The stored form of what a mute held back: empty when nothing was held."""
    muted = getattr(outcome, "muted_notification", NotificationAction.NONE)
    return "" if muted == NotificationAction.NONE else muted.value


def not_breaching(grouping_key: str) -> GroupObservation:
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
    absent: Callable[[str], GroupObservation | None] = not_breaching,
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
    admission = check.admit([observation.grouping_key for observation, _, _ in judged], now=now)
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
                labels=bounded_labels(observation.labels),
                muted_notification=muted_value(outcome),
            ),
        )
        for observation, snapshot, outcome in judged
        if observation.grouping_key in admission.admitted
    )
    return GroupDecision(verdicts=verdicts, overflowed=admission.overflowed, evicted=admission.evicted)
