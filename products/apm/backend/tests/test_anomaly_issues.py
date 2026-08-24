from parameterized import parameterized

from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.issues import (
    IssueAction,
    IssueSnapshot,
    IssueState,
    evaluate_issue_transition,
    fingerprint_for,
    required_consecutive,
)
from products.apm.backend.logic.anomaly_detection.types import Direction, SeriesKey, TrafficTier, VerdictType

CONFIG = DetectionConfig(open_after_buckets=2, resolve_after_buckets=3, reopen_window_buckets=100)

KEY = SeriesKey(namespace="prod", service="checkout", environment="us", severity="error")


def run_sequence(events: list[VerdictType | None], required: int = 2) -> list[IssueAction]:
    snapshot: IssueSnapshot | None = None
    actions = []
    for index, verdict_type in enumerate(events):
        outcome = evaluate_issue_transition(snapshot, verdict_type, index, required, CONFIG)
        snapshot = outcome.snapshot
        actions.append(outcome.action)
    return actions


SPIKE = VerdictType.SPIKE
DROP = VerdictType.DROP
SILENCE = VerdictType.SILENCE
N = None
NONE = IssueAction.NONE


class TestIssueTransitions:
    @parameterized.expand(
        [
            ("opens_after_required_consecutive", [SPIKE, SPIKE], 2, [NONE, IssueAction.OPEN]),
            ("single_blip_never_opens", [SPIKE, N, SPIKE, N], 2, [NONE, NONE, NONE, NONE]),
            ("opens_immediately_when_required_is_one", [SILENCE], 1, [IssueAction.OPEN]),
            (
                "active_records_then_resolves_after_sustained_recovery",
                [SPIKE, SPIKE, SPIKE, N, N, N],
                2,
                [NONE, IssueAction.OPEN, IssueAction.RECORD, NONE, NONE, IssueAction.RESOLVE],
            ),
            (
                "recovery_counter_resets_on_recurrence",
                [SPIKE, SPIKE, N, N, SPIKE, N, N, N],
                2,
                [NONE, IssueAction.OPEN, NONE, NONE, IssueAction.RECORD, NONE, NONE, IssueAction.RESOLVE],
            ),
            (
                "drop_deepening_into_silence_escalates_within_issue",
                [DROP, DROP, SILENCE],
                2,
                [NONE, IssueAction.OPEN, IssueAction.ESCALATE],
            ),
            (
                "silence_does_not_deescalate_to_drop",
                [SILENCE, SILENCE, DROP],
                2,
                [NONE, IssueAction.OPEN, IssueAction.RECORD],
            ),
            (
                "resolved_issue_reopens_on_recurrence",
                [SPIKE, SPIKE, N, N, N, SPIKE, SPIKE],
                2,
                [NONE, IssueAction.OPEN, NONE, NONE, IssueAction.RESOLVE, NONE, IssueAction.REOPEN],
            ),
        ]
    )
    def test_transition_sequences(
        self, _name: str, events: list[VerdictType | None], required: int, expected: list[IssueAction]
    ) -> None:
        assert run_sequence(events, required) == expected

    def test_recurrence_past_reopen_window_starts_a_fresh_issue(self) -> None:
        snapshot = IssueSnapshot(
            state=IssueState.RESOLVED,
            kind=SPIKE,
            consecutive_anomalous=0,
            consecutive_normal=5,
            last_anomalous_index=10,
            opened_at_index=1,
        )
        outcome = evaluate_issue_transition(snapshot, SPIKE, 10 + CONFIG.reopen_window_buckets + 1, 1, CONFIG)
        assert outcome.action is IssueAction.OPEN
        assert outcome.snapshot is not None
        assert outcome.snapshot.opened_at_index == 10 + CONFIG.reopen_window_buckets + 1

    def test_pending_kind_escalates_before_open(self) -> None:
        actions = run_sequence([DROP, SILENCE], required=2)
        assert actions == [NONE, IssueAction.OPEN]


class TestFingerprints:
    def test_spike_fingerprints_are_per_severity(self) -> None:
        error_key = KEY
        info_key = SeriesKey(namespace="prod", service="checkout", environment="us", severity="info")
        assert fingerprint_for(error_key, SPIKE) != fingerprint_for(info_key, SPIKE)

    @parameterized.expand([(DROP,), (SILENCE,)])
    def test_down_fingerprints_omit_severity(self, verdict_type: VerdictType) -> None:
        error_key = KEY
        info_key = SeriesKey(namespace="prod", service="checkout", environment="us", severity="info")
        fp = fingerprint_for(error_key, verdict_type)
        assert fp == fingerprint_for(info_key, verdict_type)
        assert fp.severity is None
        assert fp.direction is Direction.DOWN

    def test_drop_and_silence_share_a_fingerprint(self) -> None:
        assert fingerprint_for(KEY, DROP) == fingerprint_for(KEY, SILENCE)


class TestRequiredConsecutive:
    @parameterized.expand(
        [
            (SILENCE, TrafficTier.A, 1),
            (SILENCE, TrafficTier.B, 2),
            (SILENCE, TrafficTier.C, 3),
            (SPIKE, TrafficTier.A, 2),
            (DROP, TrafficTier.C, 2),
        ]
    )
    def test_tier_and_kind_mapping(self, verdict_type: VerdictType, tier: TrafficTier, expected: int) -> None:
        assert required_consecutive(verdict_type, tier, CONFIG) == expected
