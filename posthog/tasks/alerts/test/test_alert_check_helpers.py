from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import AlertConditionType, AlertState, InsightThresholdType

from posthog.api.test.dashboards import DashboardAPI
from posthog.tasks.alerts.test.alert_check_helpers import run_alert_check
from posthog.tasks.alerts.utils import AlertEvaluationResult, record_alert_delivery

from products.alerts.backend.destinations import AlertDelivery
from products.alerts.backend.models import AlertCheck, AlertConfiguration


class TestRunAlertCheck(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        insight = self.dashboard_api.create_insight(
            data={
                "name": "insight",
                "query": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "signed_up"}],
                },
            }
        )[1]

        alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": AlertConditionType.ABSOLUTE_VALUE},
                "calculation_interval": "daily",
                "threshold": {"configuration": {"type": InsightThresholdType.ABSOLUTE, "bounds": {"upper": 1}}},
            },
        ).json()
        self.alert_id = alert["id"]

    @patch(
        "posthog.tasks.alerts.utils.send_notifications_for_breaches",
        return_value=[AlertDelivery(channel="email", target="user1@example.com", at="2026-08-11T00:00:00+00:00")],
    )
    @patch("posthog.tasks.alerts.test.alert_check_helpers.check_alert_for_insight")
    def test_firing_path_unpacks_tuple_and_records_delivery(self, mock_check: MagicMock, mock_send: MagicMock) -> None:
        mock_check.return_value = AlertEvaluationResult(value=5.0, breaches=["breach_message"])

        run_alert_check(self.alert_id)

        alert_check = AlertCheck.objects.filter(alert_configuration=self.alert_id).latest("created_at")
        assert alert_check.state == AlertState.FIRING
        assert alert_check.calculated_value == 5.0
        assert alert_check.targets_notified == {"users": ["user1@example.com"], "destinations": []}
        assert alert_check.notification_sent_at is not None
        mock_send.assert_called_once()

    @patch("posthog.tasks.alerts.utils.send_notifications_for_breaches")
    @patch("posthog.tasks.alerts.test.alert_check_helpers.check_alert_for_insight")
    def test_not_firing_path_records_check_without_notifying(self, mock_check: MagicMock, mock_send: MagicMock) -> None:
        mock_check.return_value = AlertEvaluationResult(value=0.5, breaches=None)

        run_alert_check(self.alert_id)

        alert_check = AlertCheck.objects.filter(alert_configuration=self.alert_id).latest("created_at")
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.targets_notified == {}
        mock_send.assert_not_called()

    @patch("posthog.tasks.alerts.utils.send_notifications_for_errors", return_value=[])
    @patch("posthog.tasks.alerts.test.alert_check_helpers.check_alert_for_insight")
    def test_errored_path_records_error_without_delivery(self, mock_check: MagicMock, mock_send_err: MagicMock) -> None:
        mock_check.side_effect = RuntimeError("boom")

        run_alert_check(self.alert_id)

        alert_check = AlertCheck.objects.filter(alert_configuration=self.alert_id).latest("created_at")
        assert alert_check.state == AlertState.ERRORED
        assert alert_check.error is not None
        assert "boom" in alert_check.error["message"]
        assert alert_check.targets_notified == {}
        assert alert_check.notification_sent_at is None
        mock_send_err.assert_called_once()

    def test_record_alert_delivery_noops_on_empty_receipts(self) -> None:
        alert = AlertConfiguration.objects.get(id=self.alert_id)
        check = AlertCheck.objects.create(alert_configuration=alert, targets_notified={}, state=AlertState.ERRORED)

        assert record_alert_delivery(alert, check, []) is False

        check.refresh_from_db()
        assert check.targets_notified == {}
        assert check.notification_sent_at is None

    def test_record_alert_delivery_splits_mixed_channels(self) -> None:
        alert = AlertConfiguration.objects.get(id=self.alert_id)
        check = AlertCheck.objects.create(alert_configuration=alert, targets_notified={}, state=AlertState.FIRING)
        email = AlertDelivery(channel="email", target="a@example.com", at="2026-08-11T00:00:00+00:00")
        hog = AlertDelivery(
            channel="hog_function",
            target="Slack #eng",
            target_id="hf-1",
            template="slack",
            at="2026-08-11T00:00:00+00:00",
        )

        assert record_alert_delivery(alert, check, [email, hog]) is True

        check.refresh_from_db()
        assert check.targets_notified["users"] == ["a@example.com"]
        assert [d["target"] for d in check.targets_notified["destinations"]] == ["Slack #eng"]

    def test_record_alert_delivery_writes_legacy_map_and_receipts(self) -> None:
        alert = AlertConfiguration.objects.get(id=self.alert_id)
        check = AlertCheck.objects.create(alert_configuration=alert, targets_notified={}, state=AlertState.FIRING)
        hog = AlertDelivery(
            channel="hog_function",
            target="Slack #eng",
            target_id="hf-1",
            template="slack",
            at="2026-08-11T00:00:00+00:00",
        )

        assert record_alert_delivery(alert, check, [hog]) is True

        check.refresh_from_db()
        assert check.targets_notified == {
            "users": [],
            "destinations": [
                {
                    "channel": "hog_function",
                    "target": "Slack #eng",
                    "target_id": "hf-1",
                    "template": "slack",
                    "status": "accepted",
                    "at": "2026-08-11T00:00:00+00:00",
                }
            ],
        }
        assert check.notification_sent_at is not None
