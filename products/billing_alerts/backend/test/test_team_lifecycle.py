from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.team.team import Team

from products.alerts.backend.destinations import soft_delete_all_alert_destinations as shared_soft_delete_destinations
from products.billing_alerts.backend.alert_destinations import BILLING_ALERT_EVENT_IDS, EVENT_KIND_CONFIG
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class TestBillingAlertTeamLifecycle(BaseTest):
    def test_deleting_execution_team_rehomes_and_disables_alert(self) -> None:
        original_team_id = self.team.id
        replacement_team = Team.objects.create(organization=self.organization, name="Replacement project")
        alert = BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            name="Daily spend spike",
            enabled=True,
            state=BillingAlertConfiguration.State.FIRING,
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )
        event = BillingAlertEvent.objects.create(
            alert=alert,
            team_id=self.team.id,
            kind=BillingAlertEvent.Kind.FIRING,
            metric=BillingAlertConfiguration.Metric.SPEND,
            state_before=BillingAlertConfiguration.State.NOT_FIRING,
            state_after=BillingAlertConfiguration.State.FIRING,
            reason="Threshold breached",
        )
        destination = HogFunction.objects.create(
            team_id=self.team.id,
            name="Billing alert Slack destination",
            type="internal_destination",
            enabled=True,
            hog="",
            template_id="template-slack",
            filters={
                "events": [{"id": EVENT_KIND_CONFIG["firing"].event_id, "type": "events"}],
                "properties": [
                    {
                        "key": "alert_id",
                        "value": str(alert.id),
                        "operator": "exact",
                        "type": "event",
                    }
                ],
            },
        )

        with patch(
            "products.billing_alerts.backend.team_lifecycle.soft_delete_all_alert_destinations",
            wraps=shared_soft_delete_destinations,
        ) as soft_delete_destinations:
            self.team.delete()

        alert.refresh_from_db()
        event.refresh_from_db()
        assert alert.team_id == replacement_team.id
        assert alert.enabled is False
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert event.alert_id == alert.id
        soft_delete_destinations.assert_called_once_with(
            team_id=original_team_id,
            alert_id=str(alert.id),
            allowed_event_ids=BILLING_ALERT_EVENT_IDS,
        )
        assert HogFunction.objects.filter(id=destination.id).exists() is False

    def test_deleting_last_team_removes_alert(self) -> None:
        alert = BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            name="Daily spend spike",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )

        self.team.delete()

        assert BillingAlertConfiguration.objects.filter(id=alert.id).exists() is False
