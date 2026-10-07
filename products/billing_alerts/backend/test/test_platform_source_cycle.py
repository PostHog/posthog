from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.api import record_outcomes, slot_of
from products.alerts_platform.backend.facade.contracts import AlertEventKind, SourceBatchEvaluation, SourceKind
from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout
from products.alerts_platform.backend.facade.testing import create_configuration, set_due_at
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvaluationClaim
from products.billing_alerts.backend.platform_source_cycle import evaluate_billing_batch
from products.billing_alerts.backend.temporal.platform_evaluate import EVALUATION_BUDGET

_MODULE = "products.billing_alerts.backend.platform_source_cycle"
CUTOFF = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
DUE_AT = CUTOFF - timedelta(minutes=1)


def _billing_response(current: int | None) -> dict[str, Any]:
    customer: dict[str, Any] = {}
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
        }
        fields.update(overrides)
        return BillingAlertConfiguration.objects.create(**fields)

    def _copy(self, alert: BillingAlertConfiguration | None) -> UUID:
        with team_scope(self.team.id):
            return create_configuration(
                team=self.team,
                name="Period spend cap",
                source_kind=SourceKind.BILLING.value,
                check_interval_minutes=60,
                cooldown_minutes=0,
                next_check_at=DUE_AT,
                legacy_configuration_id=alert.id if alert else uuid4(),
            ).id

    def _evaluate(self, *responses: dict[str, Any] | Exception) -> tuple[SourceBatchEvaluation, Any]:
        side_effect = [r if isinstance(r, Exception) else (r, 12) for r in responses]
        with patch(f"{_MODULE}.fetch_billing_data", side_effect=side_effect) as fetch:
            evaluation = evaluate_billing_batch(self.team.id, slot_of(DUE_AT, CUTOFF), CUTOFF)
        return evaluation, fetch

    def test_a_breach_fires_on_the_platform_and_leaves_billings_tables_alone(self) -> None:
        alert = self._alert()
        before = BillingAlertConfiguration.objects.values("state", "next_check_at", "last_checked_at").get(id=alert.id)
        self._copy(alert)

        evaluation, _ = self._evaluate(_billing_response(150))

        (outcome,) = evaluation.outcomes
        assert (outcome.kind, outcome.new_state, outcome.value, outcome.evaluation_key) == (
            AlertEventKind.FIRING,
            "firing",
            150.0,
            f"slot:{slot_of(DUE_AT, CUTOFF)}",
        )
        assert evaluation.deliveries == ()
        assert (
            BillingAlertConfiguration.objects.values("state", "next_check_at", "last_checked_at").get(id=alert.id)
            == before
        )
        assert not BillingAlertEvaluationClaim.objects.filter(alert=alert).exists()

    @parameterized.expand(
        [
            ("no_total_yet", _billing_response(None)),
            ("billing_service_down", ConnectionError("billing service timed out")),
        ]
    )
    def test_a_check_that_reads_no_total_leaves_a_firing_alert_firing_quietly(
        self, _name: str, response: dict[str, Any] | Exception
    ) -> None:
        configuration_id = self._copy(self._alert())
        fired, _ = self._evaluate(_billing_response(150))
        with team_scope(self.team.id):
            record_outcomes(self.team.id, fired.outcomes, CUTOFF)
            set_due_at(configuration_id, DUE_AT)

        evaluation, _ = self._evaluate(response)

        (outcome,) = evaluation.outcomes
        assert (outcome.kind, outcome.new_state, outcome.consecutive_failures, outcome.disable) == (
            AlertEventKind.CHECK,
            "firing",
            0,
            False,
        )

    def test_a_snooze_set_on_the_billing_alert_holds_the_fire(self) -> None:
        self._copy(self._alert(snoozed_until=CUTOFF + timedelta(hours=2)))

        evaluation, _ = self._evaluate(_billing_response(150))

        (outcome,) = evaluation.outcomes
        assert (outcome.kind, outcome.muted_notification) == (AlertEventKind.CHECK, "fire")

    def test_one_billing_call_serves_every_alert_of_an_organization_in_a_batch(self) -> None:
        self._copy(self._alert(name="First"))
        self._copy(self._alert(name="Second"))

        evaluation, fetch = self._evaluate(_billing_response(150))

        assert fetch.call_count == 1
        assert [o.kind for o in evaluation.outcomes] == [AlertEventKind.FIRING, AlertEventKind.FIRING]

    @parameterized.expand([("gone", None, True), ("disabled", {"enabled": False}, False)])
    def test_a_copy_of_an_alert_that_cannot_run_skips_without_a_billing_call(
        self, _name: str, overrides: dict[str, Any] | None, disables_the_copy: bool
    ) -> None:
        self._copy(None if overrides is None else self._alert(**overrides))

        evaluation, fetch = self._evaluate()

        fetch.assert_not_called()
        (outcome,) = evaluation.outcomes
        assert (outcome.kind, outcome.disable) == (AlertEventKind.CHECK, disables_the_copy)


def test_the_binding_holds_the_whole_batch() -> None:
    assert source_evaluation_timeout(SourceKind.BILLING) > EVALUATION_BUDGET
