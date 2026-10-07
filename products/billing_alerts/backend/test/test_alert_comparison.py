from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest import TestCase

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import PlatformCheck, SourceCoverage
from products.alerts_platform.backend.facade.testing import undeclared_policy_divergences
from products.billing_alerts.backend.alert_comparison import BILLING_INTENTIONAL_DIVERGENCES, BillingCorrespondence
from products.billing_alerts.backend.models import (
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)
from products.billing_alerts.backend.platform_source_cycle import EvaluationAttempt

CHECKED_AT = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
EVALUATION_DATE = date(2026, 6, 22)
Status = BillingAlertEvaluationClaim.Status


def _key(number: int, *, revision: int = 1) -> str:
    return EvaluationAttempt(
        evaluation_date=EVALUATION_DATE, configuration_revision=revision, number=number
    ).evaluation_key


def _platform_check(
    legacy_configuration_id: UUID | None,
    evaluation_key: str,
    *,
    team_id: int,
    state: str = "firing",
    error_message: str = "",
) -> PlatformCheck:
    return PlatformCheck(
        team_id=team_id,
        configuration_id=uuid4(),
        legacy_configuration_id=legacy_configuration_id,
        alert_id=uuid4(),
        grouping_key="",
        evaluation_key=evaluation_key,
        kind="check",
        previous_state="not_firing",
        state=state,
        muted_notification="none",
        error_message=error_message,
        occurred_at=CHECKED_AT,
    )


class TestBillingDivergenceDeclarations(TestCase):
    def test_every_policy_divergence_is_declared(self) -> None:
        assert undeclared_policy_divergences(BillingCorrespondence()) == frozenset()


class TestBillingCorrespondence(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alert = BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Period spend cap",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE,
            threshold_value=Decimal("100"),
        )

    def _production(self, status: str, *attempts: tuple[str, timedelta]) -> list[BillingAlertEvent]:
        claim = BillingAlertEvaluationClaim.objects.create(
            alert=self.alert,
            evaluation_date=EVALUATION_DATE,
            configuration_revision=1,
            status=status,
            attempt_count=len(attempts),
        )
        events = []
        for number, (state_after, offset) in enumerate(attempts, start=1):
            event = BillingAlertEvent.objects.create(
                claim=claim,
                team_id=self.team.id,
                source=BillingAlertEvent.Source.SCHEDULED,
                attempt_number=number,
                metric=self.alert.metric,
                state_before="not_firing",
                state_after=state_after,
            )
            BillingAlertEvent.objects.filter(id=event.id).update(created_at=CHECKED_AT + offset)
            events.append(event)
        return events

    def _verdict(self, check: PlatformCheck) -> Any:
        return BillingCorrespondence().verdicts_for([check])[check.ref]

    def test_a_check_is_answered_by_the_same_attempt_at_the_same_date(self) -> None:
        first, _ = self._production(
            Status.COMPLETED, ("not_firing", -timedelta(hours=2)), ("firing", -timedelta(hours=1))
        )

        verdict = self._verdict(_platform_check(self.alert.id, _key(1), team_id=self.team.id))

        assert (verdict.coverage, verdict.state, verdict.evidence_id) == (
            SourceCoverage.EVALUATED,
            "not_firing",
            str(first.id),
        )

    @parameterized.expand([("completed", Status.COMPLETED), ("superseded", Status.SUPERSEDED)])
    def test_a_date_production_settled_sooner_answers_with_its_settled_state(self, _name: str, status: str) -> None:
        (only,) = self._production(status, ("firing", -timedelta(hours=1)))

        verdict = self._verdict(_platform_check(self.alert.id, _key(3), team_id=self.team.id))

        assert (verdict.coverage, verdict.state, verdict.evidence_id) == (
            SourceCoverage.EVALUATED,
            "firing",
            str(only.id),
        )

    @parameterized.expand(
        [
            ("an_attempt_production_has_not_made", Status.RETRYABLE, 1),
            ("a_date_production_has_not_started", None, 0),
        ]
    )
    def test_production_not_reaching_the_attempt_reads_as_behind(
        self, _name: str, status: str | None, made: int
    ) -> None:
        if status is not None:
            self._production(status, *[("not_firing", -timedelta(hours=1))] * made)

        verdict = self._verdict(_platform_check(self.alert.id, _key(2), team_id=self.team.id))

        assert (verdict.coverage, verdict.state) == (SourceCoverage.BEHIND, None)

    @parameterized.expand(
        [
            ("a_skipped_check", "slot:2026-06-23T11:59:00+00:00", True, True),
            ("no_billing_alert", _key(1), False, True),
            ("another_projects_alert", _key(1), True, False),
        ]
    )
    def test_a_check_that_names_no_production_attempt_cannot_be_answered(
        self, _name: str, key: str, names_alert: bool, same_team: bool
    ) -> None:
        check = _platform_check(
            self.alert.id if names_alert else None, key, team_id=self.team.id if same_team else self.team.id + 1
        )
        # A batch spans teams, so the alert's own team reads it in the same call.
        owner = _platform_check(self.alert.id, _key(1), team_id=self.team.id)

        assert BillingCorrespondence().verdicts_for([check, owner])[check.ref].coverage is SourceCoverage.UNKNOWN

    def test_catching_up_is_the_first_later_attempt_that_reached_the_platforms_state(self) -> None:
        self._production(
            Status.COMPLETED,
            ("not_firing", -timedelta(minutes=5)),
            ("not_firing", timedelta(minutes=10)),
            ("firing", timedelta(hours=1)),
        )

        verdict = self._verdict(_platform_check(self.alert.id, _key(1), team_id=self.team.id))

        assert verdict.state == "not_firing"
        assert verdict.caught_up_at == CHECKED_AT + timedelta(hours=1)

    def test_a_platform_failure_against_a_production_verdict_is_declared(self) -> None:
        self._production(Status.COMPLETED, ("firing", -timedelta(hours=1)))
        failed = _platform_check(
            self.alert.id, _key(1), team_id=self.team.id, state="not_firing", error_message="fetch failed"
        )
        decided = _platform_check(self.alert.id, _key(1), team_id=self.team.id, state="not_firing")

        verdicts = BillingCorrespondence().verdicts_for([failed, decided])
        (declared,) = BILLING_INTENTIONAL_DIVERGENCES

        assert declared.recognizes(failed, verdicts[failed.ref])
        assert not declared.recognizes(decided, verdicts[decided.ref])
