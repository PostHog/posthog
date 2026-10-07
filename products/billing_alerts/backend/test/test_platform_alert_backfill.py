from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.alerts_platform.backend.facade.api import due_checks
from products.alerts_platform.backend.facade.contracts import AlertEventKind, SourceKind
from products.billing_alerts.backend.models import BillingAlertConfiguration
from products.billing_alerts.backend.platform_alert_backfill import backfill_platform_billing_alert_configurations
from products.billing_alerts.backend.platform_source_cycle import evaluate_billing_batch

CUTOFF = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


@time_machine.travel(CUTOFF, tick=False)
class TestPlatformBillingAlertBackfill(BaseTest):
    def _alert(self, **overrides: Any) -> BillingAlertConfiguration:
        fields: dict[str, Any] = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "name": "Period spend cap",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE,
            "threshold_value": Decimal("100.50"),
            "minimum_value": Decimal("0"),
            "evaluation_delay_hours": 6,
            "cooldown_hours": 12,
            "next_check_at": CUTOFF - timedelta(minutes=1),
        }
        fields.update(overrides)
        return BillingAlertConfiguration.objects.create(**fields)

    def test_a_copied_alert_carries_its_bound_and_evaluates_on_the_platform(self) -> None:
        alert = self._alert(configuration_revision=3)
        self._alert(team_id=None, enabled=False)

        counts = backfill_platform_billing_alert_configurations()
        rerun = backfill_platform_billing_alert_configurations()

        assert (counts.created, counts.updated, counts.skipped) == (1, 0, 1)
        assert (rerun.created, rerun.updated) == (0, 1)
        slot = (CUTOFF - timedelta(minutes=1)).isoformat()
        (check,) = due_checks(self.team.id, SourceKind.BILLING.value, slot, CUTOFF)
        assert check.legacy_configuration_id == alert.id
        assert check.cooldown_minutes == 12 * 60
        assert check.condition == {
            "metric": "spend",
            "threshold_value": "100.500000",
            "minimum_value": "0.000000",
            "configuration_revision": 3,
        }

        response = {"customer": {"current_total_amount_usd_after_discount": "150"}}
        with patch(
            "products.billing_alerts.backend.platform_source_cycle.fetch_billing_data", return_value=(response, 9)
        ):
            evaluation = evaluate_billing_batch(self.team.id, slot, CUTOFF)

        (outcome,) = evaluation.outcomes
        assert (outcome.kind, outcome.evaluation_key) == (AlertEventKind.FIRING, "date:2026-06-22:rev:3:attempt:1")
