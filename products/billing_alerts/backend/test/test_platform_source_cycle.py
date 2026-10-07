from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.contracts import AlertEventKind, SourceKind
from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout
from products.alerts_platform.backend.facade.testing import create_configuration
from products.billing_alerts.backend.logic.state_machine import MAX_EVALUATION_ATTEMPTS, next_billing_alert_check_at
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvaluationClaim
from products.billing_alerts.backend.platform_source_cycle import evaluate_billing_batch
from products.billing_alerts.backend.temporal.platform_evaluate import EVALUATION_BUDGET

_MODULE = "products.billing_alerts.backend.platform_source_cycle"
CUTOFF = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
# A 6-hour delay at 12:00 UTC evaluates the day before 06:00 UTC, which is 2026-06-22.
EVALUATION_DATE = "2026-06-22"


def _billing_response(current: int | None) -> dict[str, Any]:
    customer: dict[str, Any] = {
        "has_active_subscription": True,
        "billing_period": {
            "current_period_start": "2026-06-01T00:00:00Z",
            "current_period_end": "2026-07-01T00:00:00Z",
        },
    }
    if current is not None:
        customer["current_total_amount_usd_after_discount"] = str(current)
    return {"customer": customer}


@time_machine.travel(CUTOFF, tick=False)
class TestPlatformBillingEvaluation(BaseTest):
    def _alert(self, **overrides: Any) -> BillingAlertConfiguration:
        fields: dict[str, Any] = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "name": "Period spend cap",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE,
            "threshold_value": Decimal("100"),
            "minimum_value": Decimal("0"),
            "evaluation_delay_hours": 6,
        }
        fields.update(overrides)
        return BillingAlertConfiguration.objects.create(**fields)

    def _copy(self, alert: BillingAlertConfiguration | None, **overrides: Any) -> None:
        fields: dict[str, Any] = {
            "team": self.team,
            "name": "Period spend cap",
            "source_kind": SourceKind.BILLING.value,
            "check_interval_minutes": 1440,
            "next_check_at": CUTOFF - timedelta(minutes=1),
            "legacy_configuration_id": alert.id if alert else uuid4(),
        }
        fields.update(overrides)
        with team_scope(self.team.id):
            create_configuration(**fields)

    def _evaluate(self, *responses: dict[str, Any] | Exception) -> tuple[Any, Any]:
        slot = (CUTOFF - timedelta(minutes=1)).isoformat()
        side_effect = [r if isinstance(r, Exception) else (r, 12) for r in responses]
        with patch(f"{_MODULE}.fetch_billing_data", side_effect=side_effect) as fetch:
            evaluation = evaluate_billing_batch(self.team.id, slot, CUTOFF)
        return evaluation, fetch

    def test_a_breach_fires_on_the_platform_and_leaves_production_alone(self) -> None:
        alert = self._alert()
        before = BillingAlertConfiguration.objects.values(
            "state", "next_check_at", "pending_evaluation_date", "retry_attempt_count"
        ).get(id=alert.id)
        self._copy(alert)

        evaluation, _ = self._evaluate(_billing_response(150))

        (outcome,) = evaluation.outcomes
        assert (outcome.kind, outcome.value, outcome.evaluation_key) == (
            AlertEventKind.FIRING,
            150.0,
            f"date:{EVALUATION_DATE}:rev:1:attempt:1",
        )
        assert outcome.next_check_at == next_billing_alert_check_at(alert, CUTOFF)
        assert outcome.source_state == {
            "evaluation_date": EVALUATION_DATE,
            "configuration_revision": 1,
            "attempt": 1,
            "completed": True,
        }
        assert evaluation.deliveries == ()
        assert (
            BillingAlertConfiguration.objects.values(
                "state", "next_check_at", "pending_evaluation_date", "retry_attempt_count"
            ).get(id=alert.id)
            == before
        )
        assert not BillingAlertEvaluationClaim.objects.filter(alert=alert).exists()

    @parameterized.expand(
        [
            ("an_inconclusive_total", _billing_response(None)),
            ("a_failed_fetch", ConnectionError("billing service timed out")),
        ]
    )
    def test_an_unsettled_check_retries_its_date_on_billings_backoff(
        self, _name: str, response: dict[str, Any] | Exception
    ) -> None:
        self._copy(
            self._alert(),
            consecutive_failures=2,
            source_state={"evaluation_date": EVALUATION_DATE, "configuration_revision": 1, "attempt": 2},
        )

        evaluation, _ = self._evaluate(response)

        (outcome,) = evaluation.outcomes
        assert outcome.evaluation_key == f"date:{EVALUATION_DATE}:rev:1:attempt:3"
        assert outcome.next_check_at == CUTOFF + timedelta(hours=1)
        assert outcome.source_state == {
            "evaluation_date": EVALUATION_DATE,
            "configuration_revision": 1,
            "attempt": 3,
            "completed": False,
        }
        assert (outcome.new_state, outcome.consecutive_failures) == ("not_firing", 2)

    def test_the_last_attempt_at_a_date_settles_it_and_counts_the_failure(self) -> None:
        alert = self._alert()
        self._copy(
            alert,
            consecutive_failures=2,
            source_state={
                "evaluation_date": EVALUATION_DATE,
                "configuration_revision": 1,
                "attempt": MAX_EVALUATION_ATTEMPTS - 1,
            },
        )

        evaluation, _ = self._evaluate(ConnectionError("billing service timed out"))

        (outcome,) = evaluation.outcomes
        assert outcome.consecutive_failures == 3
        assert outcome.next_check_at == next_billing_alert_check_at(alert, CUTOFF)
        assert outcome.source_state is not None and outcome.source_state["completed"] is True

    def test_a_settled_date_is_not_evaluated_again(self) -> None:
        alert = self._alert()
        self._copy(
            alert,
            source_state={
                "evaluation_date": EVALUATION_DATE,
                "configuration_revision": 1,
                "attempt": 1,
                "completed": True,
            },
        )

        evaluation, fetch = self._evaluate()

        fetch.assert_not_called()
        (outcome,) = evaluation.outcomes
        assert outcome.kind == AlertEventKind.CHECK
        assert outcome.next_check_at == next_billing_alert_check_at(alert, CUTOFF)

    def test_one_billing_call_serves_every_alert_of_an_organization_in_a_batch(self) -> None:
        self._copy(self._alert(name="First"))
        self._copy(self._alert(name="Second"))

        evaluation, fetch = self._evaluate(_billing_response(150))

        assert fetch.call_count == 1
        assert [o.kind for o in evaluation.outcomes] == [AlertEventKind.FIRING, AlertEventKind.FIRING]

    def test_a_copy_whose_production_alert_is_gone_is_disabled(self) -> None:
        self._copy(None)

        evaluation, fetch = self._evaluate()

        fetch.assert_not_called()
        (outcome,) = evaluation.outcomes
        assert outcome.disable is True


def test_the_binding_holds_the_whole_batch() -> None:
    assert source_evaluation_timeout(SourceKind.BILLING) > EVALUATION_BUDGET
