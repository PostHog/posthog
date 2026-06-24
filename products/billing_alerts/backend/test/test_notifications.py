from datetime import UTC, datetime
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.billing_alerts.backend.alert_destinations import BILLING_ALERT_DESTINATION_IDS_PROPERTY, EVENT_KIND_CONFIG
from products.billing_alerts.backend.logic.notifications import dispatch_billing_alert_event
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertDelivery, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


class TestBillingAlertNotifications(BaseTest):
    def _alert(self) -> BillingAlertConfiguration:
        return BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            execution_team_id=self.team.id,
            created_by_id=self.user.id,
            name="Daily spend spike",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )

    def _event(self, alert: BillingAlertConfiguration) -> BillingAlertEvent:
        return BillingAlertEvent.objects.create(
            alert=alert,
            kind=BillingAlertEvent.Kind.FIRING,
            evaluation_date=NOW.date(),
            period_start=NOW,
            period_end=NOW,
            metric=BillingAlertConfiguration.Metric.SPEND,
            state_before=BillingAlertConfiguration.State.NOT_FIRING,
            state_after=BillingAlertConfiguration.State.FIRING,
            threshold_breached=True,
            reason="Current value met threshold.",
        )

    def _destination(self, alert: BillingAlertConfiguration) -> HogFunction:
        return HogFunction.objects.create(
            team_id=alert.execution_team_id,
            name="Billing alert destination",
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

    def test_dispatch_records_delivery_and_scopes_internal_event_to_destinations(self) -> None:
        alert = self._alert()
        event = self._event(alert)
        destination = self._destination(alert)

        with patch("products.billing_alerts.backend.logic.notifications.produce_internal_event") as produce:
            dispatched = dispatch_billing_alert_event(event, now=NOW)

        event.refresh_from_db()
        alert.refresh_from_db()

        assert dispatched == 1
        assert event.notification_sent_at == NOW
        assert alert.last_notified_at == NOW
        assert BillingAlertDelivery.objects.filter(event=event, hog_function_id=destination.id).exists()

        produced_event = produce.call_args.kwargs["event"]
        assert produced_event.uuid == str(event.id)
        assert produced_event.properties[BILLING_ALERT_DESTINATION_IDS_PROPERTY] == [str(destination.id)]

    def test_dispatch_is_idempotent_once_notification_is_marked_sent(self) -> None:
        alert = self._alert()
        event = self._event(alert)
        self._destination(alert)

        with patch("products.billing_alerts.backend.logic.notifications.produce_internal_event") as produce:
            assert dispatch_billing_alert_event(event, now=NOW) == 1
            assert dispatch_billing_alert_event(event, now=NOW) == 0

        assert produce.call_count == 1
        assert BillingAlertDelivery.objects.filter(event=event).count() == 1

    def test_dispatch_failure_rolls_back_delivery_state_for_retry(self) -> None:
        alert = self._alert()
        event = self._event(alert)
        self._destination(alert)

        with patch(
            "products.billing_alerts.backend.logic.notifications.produce_internal_event",
            side_effect=RuntimeError("kafka unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                dispatch_billing_alert_event(event, now=NOW)

        event.refresh_from_db()
        alert.refresh_from_db()

        assert event.notification_sent_at is None
        assert alert.last_notified_at is None
        assert not BillingAlertDelivery.objects.filter(event=event).exists()
