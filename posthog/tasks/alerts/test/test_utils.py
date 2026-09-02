from datetime import UTC, datetime

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import AlertCalculationInterval

from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation, SloOutcome
from posthog.tasks.alerts.utils import (
    calculation_interval_to_order,
    disable_invalid_alert,
    next_check_time,
    send_notifications_for_breaches,
    send_notifications_for_errors,
    trigger_alert_hog_functions,
)

from products.alerts.backend.destinations import ActiveAlertDestination
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


class TestAlertUtils:
    def test_calculation_interval_to_order_ranks_real_time_first(self) -> None:
        assert calculation_interval_to_order(AlertCalculationInterval.REAL_TIME) < calculation_interval_to_order(
            AlertCalculationInterval.EVERY_15_MINUTES
        )

    def test_next_check_time_advances_by_2_minutes(self) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.calculation_interval = AlertCalculationInterval.REAL_TIME
        alert.next_check_at = datetime(2026, 4, 6, 14, 0, 0, tzinfo=UTC)
        alert.team = MagicMock()
        alert.team.timezone = "UTC"
        alert.schedule_restriction = None
        alert.skip_weekend = False

        with freeze_time("2026-04-06T14:00:00Z"):
            assert next_check_time(alert) == datetime(2026, 4, 6, 14, 2, 0, tzinfo=UTC)

    @parameterized.expand(
        [
            ("threshold", None, {"alert_mode": "threshold", "detector_type": None, "ensemble_operator": None}),
            (
                "detector",
                {"type": "zscore", "threshold": 0.95, "window": 30},
                {"alert_mode": "detector", "detector_type": "zscore", "ensemble_operator": None},
            ),
            (
                "ensemble",
                {
                    "type": "ensemble",
                    "operator": "AND",
                    "detectors": [
                        {"type": "zscore", "threshold": 0.95, "window": 30},
                        {"type": "mad", "threshold": 0.95, "window": 30},
                    ],
                },
                {"alert_mode": "detector", "detector_type": "ensemble", "ensemble_operator": "AND"},
            ),
        ]
    )
    @patch("posthog.tasks.alerts.utils.alert_internal_event_delivered", return_value=True)
    @patch("posthog.tasks.alerts.utils.flush_alert_internal_events")
    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event")
    @patch("posthog.tasks.alerts.utils.list_active_alert_destinations", return_value=[])
    def test_trigger_alert_hog_functions_uses_shared_delivery(
        self,
        _name: str,
        detector_config: dict | None,
        expected_props: dict,
        _mock_list: MagicMock,
        mock_produce: MagicMock,
        mock_flush: MagicMock,
        mock_delivered: MagicMock,
    ) -> None:
        mock_produce.return_value = MagicMock()
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = "firing"
        alert.last_checked_at = None
        alert.team_id = 2
        alert.team.name = "test project"
        alert.detector_config = detector_config

        trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

        props = mock_produce.call_args.kwargs["properties"]
        for key, expected_value in expected_props.items():
            assert props[key] == expected_value
        assert props["breaches"] == "test breach"
        assert "uuid" not in mock_produce.call_args.kwargs
        mock_flush.assert_not_called()
        mock_delivered.assert_not_called()

    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event", return_value=None)
    @patch("posthog.tasks.alerts.utils.list_active_alert_destinations", return_value=[])
    def test_trigger_alert_hog_functions_ignores_enqueue_failure(
        self, _mock_list: MagicMock, _mock_produce: MagicMock
    ) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.team_id = 2
        alert.last_checked_at = None
        alert.detector_config = None

        trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event", return_value=None)
    @patch("posthog.tasks.alerts.utils.list_active_alert_destinations", return_value=[])
    def test_destination_enqueue_failure_fails_delivery_slo(
        self, _mock_list: MagicMock, _mock_produce: MagicMock
    ) -> None:
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = "firing"
        alert.last_checked_at = None
        alert.team_id = 2
        alert.team.name = "test project"
        alert.detector_config = None
        capture = MagicMock()

        with slo_operation(
            spec=SloSpec(
                distinct_id=str(alert.id),
                area=SloArea.ANALYTIC_PLATFORM,
                operation=SloOperation.ALERT_DELIVERY,
                team_id=alert.team_id,
                resource_id=str(alert.id),
            ),
            capture=capture,
        ):
            trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

        completed = [call for call in capture.call_args_list if call.kwargs["event"] == "slo_operation_completed"]
        assert len(completed) == 1
        assert completed[0].kwargs["properties"]["outcome"] == SloOutcome.FAILURE
        assert completed[0].kwargs["properties"]["failure_phase"] == "destination_enqueue"

    @patch("posthog.tasks.alerts.utils.alert_internal_event_delivered", return_value=False)
    @patch("posthog.tasks.alerts.utils.flush_alert_internal_events")
    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event")
    @patch("posthog.tasks.alerts.utils.list_active_alert_destinations", return_value=[])
    def test_destination_delivery_failure_fails_delivery_slo(
        self,
        _mock_list: MagicMock,
        mock_produce: MagicMock,
        mock_flush: MagicMock,
        _mock_delivered: MagicMock,
    ) -> None:
        produce_result = MagicMock()
        mock_produce.return_value = produce_result
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = "firing"
        alert.last_checked_at = None
        alert.team_id = 2
        alert.team.name = "test project"
        alert.detector_config = None
        capture = MagicMock()

        with slo_operation(
            spec=SloSpec(
                distinct_id=str(alert.id),
                area=SloArea.ANALYTIC_PLATFORM,
                operation=SloOperation.ALERT_DELIVERY,
                team_id=alert.team_id,
                resource_id=str(alert.id),
            ),
            capture=capture,
        ):
            trigger_alert_hog_functions(alert, properties={"breaches": "test breach"})

        mock_flush.assert_called_once_with(10.0)
        completed = [call for call in capture.call_args_list if call.kwargs["event"] == "slo_operation_completed"]
        assert len(completed) == 1
        assert completed[0].kwargs["properties"]["outcome"] == SloOutcome.FAILURE
        assert completed[0].kwargs["properties"]["failure_phase"] == "notification_delivery"

    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event")
    @patch("posthog.tasks.alerts.utils.list_active_alert_destinations")
    def test_trigger_hog_functions_returns_receipt_per_destination(
        self, mock_list: MagicMock, mock_produce: MagicMock
    ) -> None:
        mock_list.return_value = [ActiveAlertDestination(id="hf-1", name="#eng-alerts", destination_type="slack")]
        mock_produce.return_value = MagicMock()  # non-None = enqueue accepted
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.name = "test alert"
        alert.insight.name = "test insight"
        alert.insight.short_id = "abcd1234"
        alert.state = "firing"
        alert.last_checked_at = None
        alert.team_id = 2
        alert.team.name = "test project"
        alert.detector_config = None

        receipts = trigger_alert_hog_functions(alert=alert, properties={"breaches": "x"})

        assert [(r.channel, r.target, r.target_id, r.template, r.status) for r in receipts] == [
            ("hog_function", "#eng-alerts", "hf-1", "slack", "accepted")
        ]

    @patch("posthog.tasks.alerts.utils.produce_alert_internal_event", return_value=None)
    @patch("posthog.tasks.alerts.utils.list_active_alert_destinations")
    def test_trigger_hog_functions_returns_empty_on_produce_failure(
        self, mock_list: MagicMock, _mock_produce: MagicMock
    ) -> None:
        mock_list.return_value = [ActiveAlertDestination(id="hf-1", name="#eng-alerts", destination_type="slack")]
        alert = MagicMock(spec=AlertConfiguration)
        alert.id = "00000000-0000-0000-0000-000000000001"
        alert.team_id = 2
        alert.last_checked_at = None
        alert.detector_config = None

        assert trigger_alert_hog_functions(alert=alert, properties={}) == []


class TestSendNotificationsReceipts(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="test alert",
            condition={"type": "absolute_value"},
            created_by=self.user,
        )
        self.alert.subscribed_users.add(self.user)

    @patch("posthog.tasks.alerts.utils.trigger_alert_hog_functions", return_value=[])
    @patch("posthog.tasks.alerts.utils.send_alert_email")
    def test_breach_notifications_return_email_receipts(self, mock_send: MagicMock, _mock_trigger: MagicMock) -> None:
        receipts = send_notifications_for_breaches(self.alert, ["breach"], idempotency_key="check-1")

        assert [(r.channel, r.target, r.status) for r in receipts] == [("email", self.user.email, "accepted")]
        mock_send.assert_called_once()

    @patch("posthog.tasks.alerts.utils.trigger_alert_hog_functions", return_value=[])
    @patch("posthog.tasks.alerts.utils.send_alert_email", side_effect=RuntimeError("smtp down"))
    def test_breach_notifications_propagate_email_failure(
        self, _mock_send: MagicMock, _mock_trigger: MagicMock
    ) -> None:
        with pytest.raises(RuntimeError):
            send_notifications_for_breaches(self.alert, ["breach"], idempotency_key="check-1")

    @patch("posthog.tasks.alerts.utils.send_alert_email")
    def test_error_notifications_return_empty_without_eligible_recipients(self, mock_send: MagicMock) -> None:
        self.alert.subscribed_users.clear()

        assert send_notifications_for_errors(self.alert, {"message": "boom"}, idempotency_key="check-1") == []
        mock_send.assert_not_called()

    @patch("posthog.tasks.alerts.utils.send_alert_email")
    def test_error_notifications_return_email_receipts(self, mock_send: MagicMock) -> None:
        receipts = send_notifications_for_errors(self.alert, {"message": "boom"}, idempotency_key="check-1")

        assert [(r.channel, r.target, r.status) for r in receipts] == [("email", self.user.email, "accepted")]
        mock_send.assert_called_once()


class TestDisableInvalidAlert(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="test alert",
            condition={"type": "absolute_value"},
            created_by=self.user,
        )
        self.alert.subscribed_users.add(self.user)

    @patch("posthog.tasks.alerts.utils.send_alert_email", side_effect=RuntimeError("smtp down"))
    def test_disable_invalid_alert_records_nothing_when_send_fails(self, _mock_send: MagicMock) -> None:
        with pytest.raises(RuntimeError):
            disable_invalid_alert(self.alert, reason="bad config")

        check = AlertCheck.objects.filter(alert_configuration=self.alert).latest("created_at")
        assert check.targets_notified == {}
        assert check.notification_sent_at is None

    @patch("posthog.tasks.alerts.utils.send_alert_email")
    def test_disable_invalid_alert_records_receipts_after_send(self, mock_send: MagicMock) -> None:
        check = disable_invalid_alert(self.alert, reason="bad config")

        check.refresh_from_db()
        assert check.targets_notified == {"users": [self.user.email], "destinations": []}
        mock_send.assert_called_once()
