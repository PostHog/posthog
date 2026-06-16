from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import AlertConditionType, AlertState, InsightThresholdType

from posthog.api.test.dashboards import DashboardAPI
from posthog.tasks.alerts.test.alert_check_helpers import run_alert_check
from posthog.tasks.alerts.utils import AlertEvaluationResult

from products.alerts.backend.models import AlertCheck


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

    @patch("posthog.tasks.alerts.utils.send_notifications_for_breaches", return_value=["user1@example.com"])
    @patch("posthog.tasks.alerts.test.alert_check_helpers.check_alert_for_insight")
    def test_firing_path_unpacks_tuple_and_records_delivery(self, mock_check: MagicMock, mock_send: MagicMock) -> None:
        mock_check.return_value = AlertEvaluationResult(value=5.0, breaches=["breach_message"])

        run_alert_check(self.alert_id)

        alert_check = AlertCheck.objects.filter(alert_configuration=self.alert_id).latest("created_at")
        assert alert_check.state == AlertState.FIRING
        assert alert_check.calculated_value == 5.0
        assert alert_check.targets_notified == {"users": [self.user.email]}
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

    @patch("posthog.tasks.alerts.utils.send_notifications_for_errors")
    @patch("posthog.tasks.alerts.test.alert_check_helpers.check_alert_for_insight")
    def test_errored_path_records_error_and_notifies(self, mock_check: MagicMock, mock_send_err: MagicMock) -> None:
        mock_check.side_effect = RuntimeError("boom")

        run_alert_check(self.alert_id)

        alert_check = AlertCheck.objects.filter(alert_configuration=self.alert_id).latest("created_at")
        assert alert_check.state == AlertState.ERRORED
        assert alert_check.error is not None
        assert "boom" in alert_check.error["message"]
        assert alert_check.targets_notified == {"users": [self.user.email]}
        mock_send_err.assert_called_once()
