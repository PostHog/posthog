from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from unittest import TestCase

from parameterized import parameterized

from products.alerts_platform.backend.comparison.divergence import Agreement, DivergenceClass, compare
from products.alerts_platform.backend.facade.contracts import (
    CheckRef,
    IntentionalDivergence,
    PlatformCheck,
    SourceCoverage,
    SourceKind,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts_platform.backend.facade.lifecycle import LOGS_ALERT_POLICY, PLATFORM_LOGS_ALERT_POLICY

AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _check(state: str, muted_notification: str = "none") -> PlatformCheck:
    return PlatformCheck(
        team_id=1,
        configuration_id=uuid4(),
        legacy_configuration_id=uuid4(),
        alert_id=uuid4(),
        grouping_key="",
        evaluation_key="window:2026-09-30T11:55:00+00:00",
        previous_state="not_firing",
        state=state,
        kind="check",
        muted_notification=muted_notification,
        error_message="",
        occurred_at=AT,
    )


class _Correspondence:
    source = SourceKind.LOGS
    production_policy = LOGS_ALERT_POLICY
    platform_policy = PLATFORM_LOGS_ALERT_POLICY
    intentional_divergences: tuple[IntentionalDivergence, ...] = (
        IntentionalDivergence(
            cause="held_announcement",
            policy_flag="mute_gates_notification_only",
            recognizes=lambda check, _verdict: check.muted_notification != "none",
            why="",
        ),
    )

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]:
        return {}


class TestDivergenceClassification(TestCase):
    @parameterized.expand(
        [
            (
                "agreed",
                _check("firing"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.EVALUATED, state="firing"),
                Agreement.AGREED,
                None,
            ),
            (
                "differing verdicts on an evaluated check",
                _check("firing"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.EVALUATED, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "a declared divergence explains the difference",
                _check("firing", muted_notification="fire"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.EVALUATED, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.INTENTIONAL,
            ),
            (
                "a declared divergence is asked before a lag",
                _check("firing", muted_notification="fire"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.BEHIND, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.INTENTIONAL,
            ),
            (
                "a declared divergence does not excuse checking an alert the source had disabled",
                _check("firing", muted_notification="fire"),
                SourceVerdict(
                    caught_up_at=None,
                    coverage=SourceCoverage.SUPPRESSED,
                    state="not_firing",
                    suppressed_by=SuppressionReason.DISABLED,
                ),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "the source has not reached this check",
                _check("firing"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.BEHIND, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.TIMING,
            ),
            (
                "the platform checked an alert the source had disabled",
                _check("firing"),
                SourceVerdict(
                    caught_up_at=None,
                    coverage=SourceCoverage.SUPPRESSED,
                    state="not_firing",
                    suppressed_by=SuppressionReason.DISABLED,
                ),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "the platform checked an alert the source had disabled, and both read not firing",
                _check("not_firing"),
                SourceVerdict(
                    caught_up_at=None,
                    coverage=SourceCoverage.SUPPRESSED,
                    state="not_firing",
                    suppressed_by=SuppressionReason.DISABLED,
                ),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "the source cannot say",
                _check("firing"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.UNKNOWN, state=None, detail="no such alert"),
                Agreement.UNCOMPARABLE,
                None,
            ),
            (
                "a lagging source that happens to hold the same verdict",
                _check("firing"),
                SourceVerdict(caught_up_at=None, coverage=SourceCoverage.BEHIND, state="firing"),
                Agreement.AGREED,
                None,
            ),
        ]
    )
    def test_classification(
        self,
        _name: str,
        check: PlatformCheck,
        verdict: SourceVerdict,
        agreement: Agreement,
        divergence: DivergenceClass | None,
    ) -> None:
        comparison = compare(check, verdict, correspondence=_Correspondence())

        assert comparison.agreement == agreement
        assert comparison.divergence == divergence
