"""Issue lifecycle as a pure state machine, one snapshot in, one outcome out —
the same shape as products/logs/backend/alert_state_machine.py. The filing
layer (not built yet) owns model mutation; nothing here touches a database.

Identity: spikes (UP) are per severity series; drops and silence (DOWN) share
a severity-less fingerprint per service, which is what lets a drop deepen into
silence within the same issue and full-service silence file one issue, not one
per severity.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.types import (
    VERDICT_DIRECTION,
    Direction,
    SeriesKey,
    TrafficTier,
    VerdictType,
)


class IssueState(StrEnum):
    PENDING = "pending"  # counting toward open; no issue row exists yet
    ACTIVE = "active"
    RESOLVED = "resolved"


class IssueAction(StrEnum):
    NONE = "none"
    OPEN = "open"
    RECORD = "record"
    ESCALATE = "escalate"  # drop deepened into silence within the same issue
    RESOLVE = "resolve"
    REOPEN = "reopen"


@dataclass(frozen=True, slots=True)
class IssueFingerprint:
    namespace: str
    service: str
    environment: str
    severity: str | None
    direction: Direction


def fingerprint_for(key: SeriesKey, verdict_type: VerdictType) -> IssueFingerprint:
    direction = VERDICT_DIRECTION[verdict_type]
    return IssueFingerprint(
        namespace=key.namespace,
        service=key.service,
        environment=key.environment,
        severity=key.severity if direction is Direction.UP else None,
        direction=direction,
    )


@dataclass(frozen=True, slots=True)
class IssueSnapshot:
    state: IssueState
    kind: VerdictType
    consecutive_anomalous: int
    consecutive_normal: int
    last_anomalous_index: int
    opened_at_index: int | None


@dataclass(frozen=True, slots=True)
class IssueOutcome:
    action: IssueAction
    snapshot: IssueSnapshot | None


def required_consecutive(verdict_type: VerdictType, tier: TrafficTier, config: DetectionConfig) -> int:
    if verdict_type is VerdictType.SILENCE:
        return config.silence_confirm_buckets.get(tier, config.open_after_buckets)
    return config.open_after_buckets


def _escalated_kind(current: VerdictType, incoming: VerdictType) -> VerdictType:
    # One-way: silence dominates drop; partial recovery does not de-escalate.
    if VerdictType.SILENCE in (current, incoming):
        return VerdictType.SILENCE
    return incoming


def evaluate_issue_transition(
    snapshot: IssueSnapshot | None,
    verdict_type: VerdictType | None,
    index: int,
    required: int,
    config: DetectionConfig,
) -> IssueOutcome:
    """Advance one fingerprint's lifecycle by one bucket.

    ``verdict_type`` is None for a normal (in-band) bucket. ``required`` is the
    consecutive-candidate count that opens (or reopens) an issue, resolved by
    the caller via ``required_consecutive`` — silence is tier-dependent.
    """
    if snapshot is None:
        if verdict_type is None:
            return IssueOutcome(IssueAction.NONE, None)
        pending = IssueSnapshot(
            state=IssueState.PENDING,
            kind=verdict_type,
            consecutive_anomalous=1,
            consecutive_normal=0,
            last_anomalous_index=index,
            opened_at_index=None,
        )
        if pending.consecutive_anomalous >= required:
            return IssueOutcome(IssueAction.OPEN, replace(pending, state=IssueState.ACTIVE, opened_at_index=index))
        return IssueOutcome(IssueAction.NONE, pending)

    if snapshot.state is IssueState.PENDING:
        if verdict_type is None:
            return IssueOutcome(IssueAction.NONE, None)
        pending = replace(
            snapshot,
            kind=_escalated_kind(snapshot.kind, verdict_type),
            consecutive_anomalous=snapshot.consecutive_anomalous + 1,
            last_anomalous_index=index,
        )
        if pending.consecutive_anomalous >= required:
            return IssueOutcome(IssueAction.OPEN, replace(pending, state=IssueState.ACTIVE, opened_at_index=index))
        return IssueOutcome(IssueAction.NONE, pending)

    if snapshot.state is IssueState.ACTIVE:
        if verdict_type is None:
            normals = snapshot.consecutive_normal + 1
            if normals >= config.resolve_after_buckets:
                return IssueOutcome(
                    IssueAction.RESOLVE,
                    replace(snapshot, state=IssueState.RESOLVED, consecutive_normal=normals, consecutive_anomalous=0),
                )
            return IssueOutcome(IssueAction.NONE, replace(snapshot, consecutive_normal=normals))
        kind = _escalated_kind(snapshot.kind, verdict_type)
        action = IssueAction.ESCALATE if kind is not snapshot.kind else IssueAction.RECORD
        return IssueOutcome(
            action,
            replace(
                snapshot,
                kind=kind,
                consecutive_anomalous=snapshot.consecutive_anomalous + 1,
                consecutive_normal=0,
                last_anomalous_index=index,
            ),
        )

    # RESOLVED
    if verdict_type is None:
        return IssueOutcome(IssueAction.NONE, snapshot)
    if index - snapshot.last_anomalous_index > config.reopen_window_buckets:
        # Recurrence past the window is a new problem: restart as fresh pending.
        return evaluate_issue_transition(None, verdict_type, index, required, config)
    reopened = replace(
        snapshot,
        kind=_escalated_kind(snapshot.kind, verdict_type),
        consecutive_anomalous=snapshot.consecutive_anomalous + 1 if snapshot.consecutive_normal == 0 else 1,
        consecutive_normal=0,
        last_anomalous_index=index,
    )
    if reopened.consecutive_anomalous >= required:
        return IssueOutcome(IssueAction.REOPEN, replace(reopened, state=IssueState.ACTIVE))
    return IssueOutcome(IssueAction.NONE, reopened)
