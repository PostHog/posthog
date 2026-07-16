from datetime import UTC, datetime
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.billing_alerts.backend.alert_destinations import EVENT_KIND_CONFIG, EventKind
from products.billing_alerts.backend.logic.notifications import (
    dispatch_billing_alert_event,
    evaluate_and_dispatch_billing_alert,
)
from products.billing_alerts.backend.logic.state_machine import commit_billing_alert_check, prepare_billing_alert_check
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def _billing_response(values: list[int]) -> dict:
    return {
        "status": "ok",
        "results": [
            {
                "id": 1,
                "label": "Total",
                "dates": ["2026-06-20", "2026-06-21", "2026-06-22"],
                "data": values,
            }
        ],
    }


class TestBillingAlertNotifications(BaseTest):
    def _alert(self, **overrides) -> BillingAlertConfiguration:
        defaults = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "name": "Daily spend spike",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            "threshold_percentage": Decimal("50"),
            "baseline_window_days": 2,
        }
        defaults.update(overrides)
        return BillingAlertConfiguration.objects.create(**defaults)

    def _destination(self, alert: BillingAlertConfiguration, event_kind: EventKind = "firing") -> HogFunction:
        return HogFunction.objects.create(
            team_id=alert.execution_team_id,
            name="Billing alert destination",
            type="internal_destination",
            enabled=True,
            hog="",
            template_id="template-slack",
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

    def test_delivery_ack_precedes_lifecycle_persistence(self) -> None:
        alert = self._alert()
        destination = self._destination(alert)
        produce_result = MagicMock()

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=produce_result,
            ) as produce,
            patch("products.billing_alerts.backend.logic.notifications.flush_alert_internal_events") as flush,
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                return_value=True,
            ) as delivered,
        ):
            event, dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                billing_response=_billing_response([60, 60, 100]),
            )

        alert.refresh_from_db()
        event.refresh_from_db()
        assert dispatched == 1
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert alert.last_notified_at == NOW
        assert event.notification_sent_at == NOW
        assert event.targets_notified == {"hog_functions": [str(destination.id)]}
        assert produce.call_args.kwargs["event_name"] == EVENT_KIND_CONFIG["firing"].event_id
        assert produce.call_args.kwargs["uuid"] == str(event.id)
        assert "billing_alert_destination_ids" not in produce.call_args.kwargs["properties"]
        flush.assert_called_once()
        delivered.assert_called_once_with(
            produce_result,
            team_id=alert.execution_team_id,
            alert_id=str(alert.id),
            event_name=EVENT_KIND_CONFIG["firing"].event_id,
        )

    def test_failed_error_delivery_preserves_last_successful_firing_state(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.FIRING, consecutive_failures=2)
        self._destination(alert, "errored")

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=MagicMock(),
            ),
            patch("products.billing_alerts.backend.logic.notifications.flush_alert_internal_events"),
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                return_value=False,
            ),
        ):
            event, dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                error=RuntimeError("billing unavailable"),
                is_transient_error=True,
            )

        alert.refresh_from_db()
        assert dispatched == 0
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert alert.consecutive_failures == 2
        assert alert.enabled is True
        assert event.kind == BillingAlertEvent.Kind.ERRORED
        assert event.state_after == BillingAlertConfiguration.State.FIRING
        assert event.notification_sent_at is None

    def test_failed_broken_delivery_keeps_alert_enabled_for_retry(self) -> None:
        alert = self._alert(consecutive_failures=4)
        self._destination(alert, "broken")

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=MagicMock(),
            ),
            patch("products.billing_alerts.backend.logic.notifications.flush_alert_internal_events"),
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                return_value=False,
            ),
        ):
            event, _ = evaluate_and_dispatch_billing_alert(alert, now=NOW, error=RuntimeError("bad config"))

        alert.refresh_from_db()
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.consecutive_failures == 4
        assert alert.enabled is True
        assert event.kind == BillingAlertEvent.Kind.BROKEN_CONFIG
        assert event.state_after == BillingAlertConfiguration.State.NOT_FIRING

    def test_acknowledged_broken_event_disables_alert(self) -> None:
        alert = self._alert(consecutive_failures=4)
        self._destination(alert, "broken")

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=MagicMock(),
            ),
            patch("products.billing_alerts.backend.logic.notifications.flush_alert_internal_events"),
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                return_value=True,
            ),
        ):
            event, dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                error=RuntimeError("bad config"),
            )

        alert.refresh_from_db()
        assert dispatched == 1
        assert alert.state == BillingAlertConfiguration.State.BROKEN
        assert alert.consecutive_failures == 5
        assert alert.enabled is False
        assert event.notification_sent_at == NOW

    def test_clear_check_skips_delivery(self) -> None:
        alert = self._alert()
        with patch("products.billing_alerts.backend.logic.notifications.produce_alert_internal_event") as produce:
            event, dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                billing_response=_billing_response([60, 60, 70]),
            )

        assert dispatched == 0
        assert event.kind == BillingAlertEvent.Kind.CHECK
        produce.assert_not_called()

    def test_stale_delivery_commit_preserves_concurrent_disable(self) -> None:
        alert = self._alert()
        check = prepare_billing_alert_check(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(
            enabled=False,
            state=BillingAlertConfiguration.State.NOT_FIRING,
            updated_at=NOW,
        )

        event = commit_billing_alert_check(check, notification_delivered=True)

        alert.refresh_from_db()
        assert alert.enabled is False
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.last_notified_at is None
        assert event.state_after == BillingAlertConfiguration.State.NOT_FIRING
        assert event.notification_sent_at == NOW

    def test_stale_delivery_commit_preserves_concurrent_snooze(self) -> None:
        alert = self._alert()
        check = prepare_billing_alert_check(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        snooze_until = NOW.replace(day=24)
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(
            state=BillingAlertConfiguration.State.SNOOZED,
            snooze_until=snooze_until,
            updated_at=NOW,
        )

        commit_billing_alert_check(check, notification_delivered=True)

        alert.refresh_from_db()
        assert alert.state == BillingAlertConfiguration.State.SNOOZED
        assert alert.snooze_until == snooze_until
        assert alert.last_notified_at is None

    def test_stale_delivery_commit_preserves_concurrent_threshold_reset(self) -> None:
        alert = self._alert()
        check = prepare_billing_alert_check(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(
            threshold_percentage=Decimal("75"),
            state=BillingAlertConfiguration.State.NOT_FIRING,
            updated_at=NOW,
        )

        commit_billing_alert_check(check, notification_delivered=True)

        alert.refresh_from_db()
        assert alert.threshold_percentage == Decimal("75")
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.last_notified_at is None

    def test_compatibility_dispatch_is_idempotent(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.FIRING)
        destination = self._destination(alert)
        event = BillingAlertEvent.objects.create(
            alert=alert,
            team_id=alert.team_id,
            kind=BillingAlertEvent.Kind.FIRING,
            metric=alert.metric,
            state_before=BillingAlertConfiguration.State.NOT_FIRING,
            state_after=BillingAlertConfiguration.State.FIRING,
        )

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=MagicMock(),
            ) as produce,
            patch("products.billing_alerts.backend.logic.notifications.flush_alert_internal_events"),
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                return_value=True,
            ),
        ):
            assert dispatch_billing_alert_event(event, now=NOW) == 1
            assert dispatch_billing_alert_event(event, now=NOW) == 0

        event.refresh_from_db()
        assert produce.call_count == 1
        assert event.targets_notified == {"hog_functions": [str(destination.id)]}
