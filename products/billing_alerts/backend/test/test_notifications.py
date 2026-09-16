from datetime import UTC, datetime
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.utils import absolute_uri

from products.billing_alerts.backend.alert_destinations import EVENT_KIND_CONFIG, EventKind
from products.billing_alerts.backend.logic.notifications import (
    commit_pending_billing_alert_dispatch,
    evaluate_and_dispatch_billing_alert,
    prepare_billing_alert_dispatch,
)
from products.billing_alerts.backend.logic.state_machine import (
    BillingAlertConfigurationChanged,
    BillingAlertEvaluationInProgress,
    commit_billing_alert_check,
    prepare_billing_alert_check,
)
from products.billing_alerts.backend.models import (
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def _billing_response(current: int) -> dict:
    return {
        "customer": {
            "has_active_subscription": True,
            "billing_period": {
                "current_period_start": "2026-06-01T00:00:00Z",
                "current_period_end": "2026-07-01T00:00:00Z",
                "interval": "month",
            },
            "current_total_amount_usd_after_discount": str(current),
            "projected_total_amount_usd_with_limit_after_discount": str(current),
        }
    }


class TestBillingAlertNotifications(BaseTest):
    def _alert(self, **overrides) -> BillingAlertConfiguration:
        defaults = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "name": "Period spend cap",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE,
            "threshold_value": Decimal("100"),
        }
        defaults.update(overrides)
        return BillingAlertConfiguration.objects.create(**defaults)

    def _destination(self, alert: BillingAlertConfiguration, event_kind: EventKind = "firing") -> HogFunction:
        destinations = {
            kind: HogFunction.objects.create(
                team_id=alert.execution_team_id,
                name="Billing alert destination",
                type="internal_destination",
                enabled=True,
                hog="",
                template_id="template-slack",
                filters={
                    "events": [{"id": config.event_id, "type": "events"}],
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
            for kind, config in EVENT_KIND_CONFIG.items()
        }
        return destinations[event_kind]

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
                billing_response=_billing_response(100),
            )

        alert.refresh_from_db()
        event.refresh_from_db()
        assert dispatched == 1
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert alert.last_notified_at == NOW
        assert event.notification_sent_at == NOW
        assert event.targets_notified == {"hog_functions": [str(destination.id)]}
        assert produce.call_args.kwargs["event_name"] == EVENT_KIND_CONFIG["firing"].event_id
        assert produce.call_args.kwargs["uuid"] == str(event.claim.delivery_uuid)
        assert produce.call_args.kwargs["properties"]["alert_url"] == absolute_uri("/organization/billing/alerts")
        assert "billing_alert_destination_ids" not in produce.call_args.kwargs["properties"]
        flush.assert_called_once()
        delivered.assert_called_once_with(
            produce_result,
            team_id=alert.execution_team_id,
            alert_id=str(alert.id),
            event_name=EVENT_KIND_CONFIG["firing"].event_id,
        )

    def test_no_destination_commits_event_without_starting_cooldown(self) -> None:
        alert = self._alert()
        produce_result = MagicMock()

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=produce_result,
            ) as produce,
            patch("products.billing_alerts.backend.logic.notifications.flush_alert_internal_events"),
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                return_value=True,
            ) as delivered,
        ):
            event, dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                billing_response=_billing_response(100),
            )

        alert.refresh_from_db()
        # The internal event is still emitted and the alert transitions to firing, but with no
        # destination target nothing was delivered: cooldown must not start, so a destination
        # added later is not suppressed.
        assert dispatched == 0
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert event.notification_sent_at is None
        assert event.targets_notified == {}
        assert alert.last_notified_at is None
        produce.assert_called_once()
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
        assert event.error_message == "Billing alert evaluation failed."
        assert "billing unavailable" not in event.error_message

    def test_same_day_retry_of_delivered_error_does_not_renotify(self) -> None:
        alert = self._alert()
        self._destination(alert, "errored")

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
            first_event, first_dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                error=RuntimeError("billing unavailable"),
                is_transient_error=True,
            )
            second_event, second_dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW.replace(minute=16),
                error=RuntimeError("billing unavailable"),
                is_transient_error=True,
            )

        alert.refresh_from_db()
        assert first_dispatched == 1
        assert first_event.notification_sent_at == NOW
        # The user already received this evaluation date's error, so the retry keeps its event row
        # for attempt history but sends nothing.
        assert produce.call_count == 1
        assert second_dispatched == 0
        assert second_event.kind == BillingAlertEvent.Kind.ERRORED
        assert second_event.notification_sent_at is None
        assert alert.enabled is True

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
                billing_response=_billing_response(70),
            )

        assert dispatched == 0
        assert event.kind == BillingAlertEvent.Kind.CHECK
        produce.assert_not_called()

    def test_stale_delivery_commit_is_fenced_after_concurrent_disable(self) -> None:
        alert = self._alert()
        check = prepare_billing_alert_check(
            alert,
            source=BillingAlertEvent.Source.SCHEDULED,
            now=NOW,
            billing_response=_billing_response(100),
        )
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(
            enabled=False,
            state=BillingAlertConfiguration.State.NOT_FIRING,
            configuration_revision=alert.configuration_revision + 1,
            updated_at=NOW,
        )

        with self.assertRaises(BillingAlertConfigurationChanged):
            commit_billing_alert_check(check, notification_delivered=True)

        alert.refresh_from_db()
        assert alert.enabled is False
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.last_notified_at is None
        assert BillingAlertEvent.objects.filter(claim__alert=alert).exists() is False

    def test_stale_delivery_commit_preserves_concurrent_snooze(self) -> None:
        alert = self._alert()
        check = prepare_billing_alert_check(
            alert,
            source=BillingAlertEvent.Source.SCHEDULED,
            now=NOW,
            billing_response=_billing_response(100),
        )
        snoozed_until = NOW.replace(day=24)
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(
            state=BillingAlertConfiguration.State.SNOOZED,
            snoozed_until=snoozed_until,
            configuration_revision=alert.configuration_revision + 1,
            updated_at=NOW,
        )

        with self.assertRaises(BillingAlertConfigurationChanged):
            commit_billing_alert_check(check, notification_delivered=True)

        alert.refresh_from_db()
        assert alert.state == BillingAlertConfiguration.State.SNOOZED
        assert alert.snoozed_until == snoozed_until
        assert alert.last_notified_at is None

    def test_stale_delivery_commit_preserves_concurrent_threshold_reset(self) -> None:
        alert = self._alert()
        check = prepare_billing_alert_check(
            alert,
            source=BillingAlertEvent.Source.SCHEDULED,
            now=NOW,
            billing_response=_billing_response(100),
        )
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(
            threshold_percentage=Decimal("75"),
            state=BillingAlertConfiguration.State.NOT_FIRING,
            configuration_revision=alert.configuration_revision + 1,
            updated_at=NOW,
        )

        with self.assertRaises(BillingAlertConfigurationChanged):
            commit_billing_alert_check(check, notification_delivered=True)

        alert.refresh_from_db()
        assert alert.threshold_percentage == Decimal("75")
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.last_notified_at is None

    def test_configuration_change_is_fenced_before_notification_production(self) -> None:
        alert = self._alert()
        self._destination(alert)
        dispatch = prepare_billing_alert_dispatch(
            alert,
            now=NOW,
            billing_response=_billing_response(100),
        )
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(
            configuration_revision=alert.configuration_revision + 1,
            threshold_percentage=Decimal("75"),
        )

        with (
            patch("products.billing_alerts.backend.logic.notifications.produce_alert_internal_event") as produce,
            self.assertRaises(BillingAlertConfigurationChanged),
        ):
            commit_pending_billing_alert_dispatch(dispatch)

        produce.assert_not_called()

    def test_lease_takeover_fences_stale_worker_commit(self) -> None:
        alert = self._alert()
        check = prepare_billing_alert_check(
            alert,
            source=BillingAlertEvent.Source.SCHEDULED,
            now=NOW,
            billing_response=_billing_response(100),
        )
        BillingAlertEvaluationClaim.objects.filter(pk=check.claim.pk).update(attempt_count=2)

        with self.assertRaises(BillingAlertEvaluationInProgress):
            commit_billing_alert_check(check, notification_delivered=True)

        assert BillingAlertEvent.objects.filter(claim__alert=alert).exists() is False

    def test_retry_reuses_delivery_uuid_and_preserves_attempt_history(self) -> None:
        alert = self._alert()
        self._destination(alert)

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=MagicMock(),
            ) as produce,
            patch("products.billing_alerts.backend.logic.notifications.flush_alert_internal_events"),
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                side_effect=[False, True],
            ),
        ):
            first_event, first_dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                billing_response=_billing_response(100),
            )
            with self.assertRaises(BillingAlertEvaluationInProgress):
                evaluate_and_dispatch_billing_alert(
                    alert,
                    now=NOW.replace(minute=10),
                    billing_response=_billing_response(100),
                )
            second_event, second_dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW.replace(minute=16),
                billing_response=_billing_response(100),
            )

        claim = BillingAlertEvaluationClaim.objects.get(alert=alert)
        assert first_dispatched == 0
        assert second_dispatched == 1
        assert first_event.attempt_number == 1
        assert second_event.attempt_number == 2
        assert BillingAlertEvent.objects.filter(claim=claim).count() == 2
        assert [call.kwargs["uuid"] for call in produce.call_args_list] == [
            str(claim.delivery_uuid),
            str(claim.delivery_uuid),
        ]

    def test_incomplete_destination_group_is_not_dispatched(self) -> None:
        alert = self._alert()
        HogFunction.objects.create(
            team_id=alert.execution_team_id,
            name="Incomplete billing destination",
            type="internal_destination",
            enabled=True,
            hog="",
            template_id="template-slack",
            filters={
                "events": [{"id": EVENT_KIND_CONFIG["firing"].event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": str(alert.id), "type": "event"}],
            },
        )

        with patch("products.billing_alerts.backend.logic.notifications.produce_alert_internal_event") as produce:
            event, dispatched = evaluate_and_dispatch_billing_alert(
                alert,
                now=NOW,
                billing_response=_billing_response(100),
            )

        assert dispatched == 0
        assert event.notification_sent_at is None
        produce.assert_not_called()
