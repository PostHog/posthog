from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from unittest import TestCase
from unittest.mock import patch

from products.alerts_platform.backend.comparison.orchestration import run_comparison
from products.alerts_platform.backend.comparison.platform_history import ComparisonWindowTooLarge
from products.alerts_platform.backend.facade.contracts import (
    CheckRef,
    IntentionalDivergence,
    PlatformCheck,
    SourceCoverage,
    SourceKind,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts_platform.backend.facade.lifecycle import LOGS_ALERT_POLICY

SINCE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
UNTIL = SINCE + timedelta(hours=1)
READER = "products.alerts_platform.backend.comparison.orchestration.read_platform_checks"


def _check(state: str) -> PlatformCheck:
    return PlatformCheck(
        team_id=1,
        configuration_id=uuid4(),
        legacy_configuration_id=uuid4(),
        alert_id=uuid4(),
        grouping_key="",
        evaluation_key="window:2026-10-01T12:59:00+00:00",
        kind="check",
        previous_state="not_firing",
        state=state,
        muted_notification="none",
        error_message="",
        occurred_at=SINCE,
    )


class _Correspondence:
    source = SourceKind.LOGS
    production_policy = LOGS_ALERT_POLICY
    platform_policy = LOGS_ALERT_POLICY
    intentional_divergences: tuple[IntentionalDivergence, ...] = ()

    def __init__(
        self,
        states: dict[CheckRef, str] | None = None,
        *,
        verdicts: dict[CheckRef, SourceVerdict] | None = None,
    ) -> None:
        self._verdicts = verdicts or {
            ref: SourceVerdict(caught_up_at=None, coverage=SourceCoverage.EVALUATED, state=state)
            for ref, state in (states or {}).items()
        }

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]:
        return {check.ref: self._verdicts[check.ref] for check in checks if check.ref in self._verdicts}


class TestRunComparison(TestCase):
    def test_a_check_the_source_left_unanswered_is_not_counted_as_agreement(self) -> None:
        # The contract obliges a correspondence to answer every ref. A source that under-answers
        # would otherwise lift the agreement rate by shrinking its own denominator.
        checks = [_check("firing"), _check("firing")]
        answered = {checks[0].ref: "firing"}

        with patch(READER, autospec=True, return_value=checks):
            run = run_comparison(correspondence=_Correspondence(answered), team_ids=[1], since=SINCE, until=UNTIL)

        assert run.checks == 2
        assert run.by_coverage[SourceCoverage.UNKNOWN] == 1
        assert run.agreement_rate == 1.0

    def test_a_team_whose_window_is_too_large_does_not_cost_the_sweep(self) -> None:
        checks = [_check("firing")]

        def read(*, team_id: int, **_: object) -> Sequence[PlatformCheck]:
            if team_id == 1:
                raise ComparisonWindowTooLarge("narrow it")
            return checks

        with patch(READER, autospec=True, side_effect=read):
            run = run_comparison(
                correspondence=_Correspondence({checks[0].ref: "firing"}),
                team_ids=[1, 2],
                since=SINCE,
                until=UNTIL,
            )

        assert set(run.teams_unread) == {1}
        assert run.teams_read == 1
        assert run.checks == 1

    def test_a_team_named_twice_is_swept_once(self) -> None:
        # A sweep built from a query missing a DISTINCT would otherwise count a team's checks
        # twice, into both halves of the rate.
        checks = [_check("firing")]

        with patch(READER, autospec=True, return_value=checks):
            run = run_comparison(
                correspondence=_Correspondence({checks[0].ref: "firing"}),
                team_ids=[1, 1],
                since=SINCE,
                until=UNTIL,
            )

        assert run.checks == 1
        assert run.teams_read == 1

    def test_a_real_divergence_records_how_long_the_source_took_to_reach_the_same_verdict(self) -> None:
        # The number a first run exists to produce: a REAL the source caught up to four minutes
        # later is two cadences out of phase, and one it never caught up to is a disagreement.
        lagging, disagreeing, misdated, drifted = (_check("firing") for _ in range(4))
        verdicts = {
            lagging.ref: SourceVerdict(
                coverage=SourceCoverage.EVALUATED,
                state="not_firing",
                caught_up_at=SINCE + timedelta(minutes=4),
            ),
            disagreeing.ref: SourceVerdict(caught_up_at=None, coverage=SourceCoverage.EVALUATED, state="not_firing"),
            # A correspondence that dated its own scan wrong, which must not read as a short lag.
            misdated.ref: SourceVerdict(
                coverage=SourceCoverage.EVALUATED,
                state="not_firing",
                caught_up_at=SINCE - timedelta(minutes=4),
            ),
            # A disabled alert the platform still checked. Its next move into the state is no lag.
            drifted.ref: SourceVerdict(
                coverage=SourceCoverage.SUPPRESSED,
                state="not_firing",
                suppressed_by=SuppressionReason.DISABLED,
                caught_up_at=SINCE + timedelta(minutes=4),
            ),
        }

        with patch(READER, autospec=True, return_value=[lagging, disagreeing, misdated, drifted]):
            run = run_comparison(
                correspondence=_Correspondence(verdicts=verdicts), team_ids=[1], since=SINCE, until=UNTIL
            )

        assert run.by_divergence == {"real": 4}
        assert run.real_caught_up_within == {"5m": 1, "never": 2, "source_suppressed": 1}

    def test_a_check_too_recent_to_have_settled_is_pending_rather_than_a_disagreement(self) -> None:
        # Booking these as disagreement inflates the one bucket worth acting on.
        recent = _check("firing")
        verdicts = {recent.ref: SourceVerdict(caught_up_at=None, coverage=SourceCoverage.EVALUATED, state="not_firing")}

        with patch(READER, autospec=True, return_value=[recent]):
            run = run_comparison(
                correspondence=_Correspondence(verdicts=verdicts),
                team_ids=[1],
                since=SINCE - timedelta(hours=1),
                until=SINCE + timedelta(minutes=1),
                settle_for=timedelta(minutes=15),
            )

        assert run.real_caught_up_within == {"pending": 1}

    def test_the_rate_measures_agreement_rather_than_how_much_the_source_could_answer(self) -> None:
        # Counting UNCOMPARABLE against agreement would make the headline number track backfill
        # completeness instead, which is the trap this run reports `by_coverage` separately to avoid.
        checks = [_check("firing"), _check("firing"), _check("not_firing")]
        answered = {checks[0].ref: "firing", checks[2].ref: "firing"}

        with patch(READER, autospec=True, return_value=checks):
            run = run_comparison(correspondence=_Correspondence(answered), team_ids=[1], since=SINCE, until=UNTIL)

        assert run.agreement_rate == 0.5
        assert run.by_coverage[SourceCoverage.UNKNOWN] == 1
        assert len(run.divergences) == 1
