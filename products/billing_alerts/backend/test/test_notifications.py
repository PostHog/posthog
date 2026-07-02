from datetime import UTC, datetime
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.billing_alerts.backend.alert_destinations import (
    BILLING_ALERT_DESTINATION_IDS_PROPERTY,
    EVENT_KIND_CONFIG,
    EventKind,
)
from products.billing_alerts.backend.logic.notifications import dispatch_billing_alert_event
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


class TestBillingAlertNotifications(BaseTest):
    def _alert(self) -> BillingAlertConfiguration:
        return BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Daily spend spike",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )

    def _event(
        self,
        alert: BillingAlertConfiguration,
        kind: str = BillingAlertEvent.Kind.FIRING,
    ) -> BillingAlertEvent:
        return BillingAlertEvent.objects.create(
            alert=alert,
            team_id=alert.team_id,
            kind=kind,
            evaluation_date=NOW.date(),
            period_start=NOW,
            period_end=NOW,
            metric=BillingAlertConfiguration.Metric.SPEND,
            state_before=BillingAlertConfiguration.State.NOT_FIRING,
            state_after=BillingAlertConfiguration.State.FIRING,
            threshold_breached=kind == BillingAlertEvent.Kind.FIRING,
            error_message="Billing service unavailable."
            if kind in (BillingAlertEvent.Kind.ERRORED, BillingAlertEvent.Kind.BROKEN_CONFIG)
            else None,
            reason="Current value met threshold.",
        )

    def _destination(
        self,
        alert: BillingAlertConfiguration,
        template_id: str,
        event_kind: EventKind = "firing",
    ) -> HogFunction:
        return HogFunction.objects.create(
            team_id=alert.execution_team_id,
            name="Billing alert destination",
            type="internal_destination",
            enabled=True,
            hog="",
            template_id=template_id,
            filters={
                "events": [{"id": EVENT_KIND_CONFIG[event_kind].event_id, "type": "events"}],
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

    @parameterized.expand(
        [
            ("slack", "template-slack"),
            ("webhook", "template-webhook"),
            ("teams", "template-microsoft-teams"),
        ]
    )
    def test_dispatch_marks_event_and_scopes_internal_event_to_destination(
        self, _destination_type: str, template_id: str
    ) -> None:
        alert = self._alert()
        event = self._event(alert)
        destination = self._destination(alert, template_id)

        with patch("posthog.alerting.destinations.produce_internal_event") as produce:
            with self.captureOnCommitCallbacks(execute=True):
                dispatched = dispatch_billing_alert_event(event, now=NOW)

        event.refresh_from_db()
        alert.refresh_from_db()

        assert dispatched == 1
        assert event.notification_sent_at == NOW
        assert event.targets_notified == {"hog_functions": [str(destination.id)]}
        assert alert.last_notified_at == NOW

        produced_event = produce.call_args.kwargs["event"]
        assert produced_event.uuid == str(event.id)
        assert produced_event.properties[BILLING_ALERT_DESTINATION_IDS_PROPERTY] == [str(destination.id)]

    @parameterized.expand(
        [
            ("firing", BillingAlertEvent.Kind.FIRING),
            ("resolved", BillingAlertEvent.Kind.RESOLVED),
            ("errored", BillingAlertEvent.Kind.ERRORED),
            ("broken", BillingAlertEvent.Kind.BROKEN_CONFIG),
        ]
    )
    def test_dispatch_emits_supported_event_kinds(
        self, destination_event_kind: EventKind, model_event_kind: str
    ) -> None:
        alert = self._alert()
        event = self._event(alert, model_event_kind)
        self._destination(alert, "template-slack", destination_event_kind)

        with patch("posthog.alerting.destinations.produce_internal_event") as produce:
            with self.captureOnCommitCallbacks(execute=True):
                assert dispatch_billing_alert_event(event, now=NOW) == 1

        produced_event = produce.call_args.kwargs["event"]
        assert produced_event.event == EVENT_KIND_CONFIG[destination_event_kind].event_id

    def test_dispatch_is_idempotent_once_notification_is_marked_sent(self) -> None:
        alert = self._alert()
        event = self._event(alert)
        destination = self._destination(alert, "template-slack")

        with patch("posthog.alerting.destinations.produce_internal_event") as produce:
            with self.captureOnCommitCallbacks(execute=True):
                assert dispatch_billing_alert_event(event, now=NOW) == 1
            assert dispatch_billing_alert_event(event, now=NOW) == 0

        assert produce.call_count == 1
        event.refresh_from_db()
        assert event.targets_notified == {"hog_functions": [str(destination.id)]}

    def test_dispatch_is_idempotent_once_targets_are_marked_notified(self) -> None:
        alert = self._alert()
        event = self._event(alert)
        destination = self._destination(alert, "template-slack")
        BillingAlertEvent.objects.filter(id=event.id).update(targets_notified={"hog_functions": [str(destination.id)]})

        with patch("posthog.alerting.destinations.produce_internal_event") as produce:
            assert dispatch_billing_alert_event(event, now=NOW) == 0

        produce.assert_not_called()

    def test_dispatch_failure_rolls_back_notification_state_for_retry(self) -> None:
        alert = self._alert()
        event = self._event(alert)
        self._destination(alert, "template-slack")

        with self.assertRaises(RuntimeError):
            with patch(
                "posthog.alerting.destinations.produce_internal_event",
                side_effect=RuntimeError("kafka unavailable"),
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    dispatch_billing_alert_event(event, now=NOW)

        event.refresh_from_db()
        alert.refresh_from_db()

        assert event.notification_sent_at is None
        assert event.targets_notified == {}
        assert alert.last_notified_at is None
