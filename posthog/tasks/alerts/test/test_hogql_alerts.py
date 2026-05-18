from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin
from unittest.mock import ANY, MagicMock, patch

import dateutil
from parameterized import parameterized

from posthog.schema import AlertCalculationInterval, AlertConditionType, AlertState, HogQLQuery, InsightThresholdType

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.checks import check_alert

FROZEN_TIME = dateutil.parser.parse("2024-06-02T08:55:00.000Z")


@freeze_time(FROZEN_TIME)
@patch("posthog.api.alert.posthoganalytics.feature_enabled", return_value=True)
@patch("posthog.tasks.alerts.utils.send_notifications_for_errors", return_value=[])
@patch("posthog.tasks.alerts.utils.send_notifications_for_breaches", return_value=[])
class TestHogQLAlerts(APIBaseTest, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def create_hogql_insight(self, sql: str) -> dict[str, Any]:
        query_dict = HogQLQuery(query=sql).model_dump()
        insight = self.dashboard_api.create_insight(
            data={
                "name": "hogql insight",
                "query": query_dict,
            }
        )[1]
        return insight

    def create_alert(
        self,
        insight: dict,
        *,
        condition_type: AlertConditionType = AlertConditionType.ABSOLUTE_VALUE,
        threshold_type: InsightThresholdType = InsightThresholdType.ABSOLUTE,
        lower: Optional[float] = None,
        upper: Optional[float] = None,
        calculation_interval: AlertCalculationInterval = AlertCalculationInterval.DAILY,
    ) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "config": {"type": "HogQLAlertConfig"},
                "condition": {"type": condition_type.value},
                "calculation_interval": calculation_interval,
                "threshold": {
                    "configuration": {
                        "type": threshold_type.value,
                        "bounds": {"lower": lower, "upper": upper},
                    }
                },
            },
        )
        assert response.status_code == 201, response.content
        return response.json()

    # --- Absolute value ----------------------------------------------------

    @parameterized.expand(
        [
            ("breach_lower", "SELECT 0", 1.0, None, AlertState.FIRING, 0.0, "less than lower threshold (1.0)"),
            ("breach_upper", "SELECT 7", None, 5.0, AlertState.FIRING, 7.0, "more than upper threshold (5.0)"),
            ("within_bounds", "SELECT 3", 1.0, 5.0, AlertState.NOT_FIRING, 3.0, None),
            (
                "uses_last_row_of_time_series",
                "SELECT value FROM (SELECT 1 AS value UNION ALL SELECT 99 AS value) ORDER BY value ASC",
                None,
                10.0,
                AlertState.FIRING,
                99.0,
                "more than upper threshold (10.0)",
            ),
        ]
    )
    def test_absolute_value(
        self,
        _name: str,
        sql: str,
        lower: Optional[float],
        upper: Optional[float],
        expected_state: AlertState,
        expected_value: float,
        expected_message_fragment: Optional[str],
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
    ) -> None:
        insight = self.create_hogql_insight(sql)
        alert = self.create_alert(insight, lower=lower, upper=upper)

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == expected_state

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == expected_value
        assert alert_check.state == expected_state
        assert alert_check.error is None

        if expected_message_fragment is None:
            mock_send_breaches.assert_not_called()
        else:
            mock_send_breaches.assert_called_once()
            args = mock_send_breaches.call_args.args
            breaches = args[1]
            assert len(breaches) == 1
            assert expected_message_fragment in breaches[0]

    # --- Relative conditions ----------------------------------------------

    @parameterized.expand(
        [
            (
                "relative_increase_absolute_breach",
                "SELECT value FROM (SELECT 10 AS value, 1 AS ord UNION ALL SELECT 25 AS value, 2 AS ord) ORDER BY ord",
                AlertConditionType.RELATIVE_INCREASE,
                InsightThresholdType.ABSOLUTE,
                None,
                10.0,
                AlertState.FIRING,
                15.0,
                "more than upper threshold (10.0)",
            ),
            (
                "relative_increase_percentage_breach",
                "SELECT value FROM (SELECT 10 AS value, 1 AS ord UNION ALL SELECT 20 AS value, 2 AS ord) ORDER BY ord",
                AlertConditionType.RELATIVE_INCREASE,
                InsightThresholdType.PERCENTAGE,
                None,
                0.5,
                AlertState.FIRING,
                1.0,
                "more than upper threshold",
            ),
            (
                "relative_decrease_absolute_breach",
                "SELECT value FROM (SELECT 20 AS value, 1 AS ord UNION ALL SELECT 5 AS value, 2 AS ord) ORDER BY ord",
                AlertConditionType.RELATIVE_DECREASE,
                InsightThresholdType.ABSOLUTE,
                None,
                10.0,
                AlertState.FIRING,
                15.0,
                "more than upper threshold (10.0)",
            ),
            (
                "relative_increase_no_breach",
                "SELECT value FROM (SELECT 10 AS value, 1 AS ord UNION ALL SELECT 11 AS value, 2 AS ord) ORDER BY ord",
                AlertConditionType.RELATIVE_INCREASE,
                InsightThresholdType.ABSOLUTE,
                None,
                10.0,
                AlertState.NOT_FIRING,
                1.0,
                None,
            ),
        ]
    )
    def test_relative(
        self,
        _name: str,
        sql: str,
        condition_type: AlertConditionType,
        threshold_type: InsightThresholdType,
        lower: Optional[float],
        upper: Optional[float],
        expected_state: AlertState,
        expected_value: float,
        expected_message_fragment: Optional[str],
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
    ) -> None:
        insight = self.create_hogql_insight(sql)
        alert = self.create_alert(
            insight,
            condition_type=condition_type,
            threshold_type=threshold_type,
            lower=lower,
            upper=upper,
        )

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == expected_state

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == expected_value
        assert alert_check.state == expected_state

        if expected_message_fragment is None:
            mock_send_breaches.assert_not_called()
        else:
            mock_send_breaches.assert_called_once()
            args = mock_send_breaches.call_args.args
            breaches = args[1]
            assert expected_message_fragment in breaches[0]

    # --- Validation errors ------------------------------------------------

    def test_relative_with_single_row_errors(
        self,
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
    ) -> None:
        insight = self.create_hogql_insight("SELECT 1")
        alert = self.create_alert(insight, condition_type=AlertConditionType.RELATIVE_INCREASE, upper=1.0)

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.ERRORED

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.error is not None
        assert "at least two rows" in alert_check.error["message"]
        mock_send_errors.assert_called_once_with(ANY, alert_check.error)

    def test_multi_column_query_errors(
        self,
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
    ) -> None:
        insight = self.create_hogql_insight("SELECT 1, 2")
        alert = self.create_alert(insight, upper=10)

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.ERRORED

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.error is not None
        assert "exactly one column" in alert_check.error["message"]

    def test_non_numeric_column_errors(
        self,
        mock_send_breaches: MagicMock,
        mock_send_errors: MagicMock,
        mock_feature_enabled: MagicMock,
    ) -> None:
        insight = self.create_hogql_insight("SELECT 'hello'")
        alert = self.create_alert(insight, upper=10)

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.ERRORED

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.error is not None
        assert "numeric column" in alert_check.error["message"]


@freeze_time(FROZEN_TIME)
class TestAlertCreationGate(APIBaseTest, ClickhouseDestroyTablesMixin):
    """Verifies the alert-creation API gate: accepts HogQL when flag is on, rejects when off,
    still rejects truly unsupported kinds (Funnels)."""

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def _create_hogql_insight(self, sql: str = "SELECT 1") -> dict[str, Any]:
        return self.dashboard_api.create_insight(
            data={"name": "hogql", "query": HogQLQuery(query=sql).model_dump()}
        )[1]

    def _post_alert(self, insight_id: int) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": insight_id,
                "subscribed_users": [self.user.id],
                "config": {"type": "HogQLAlertConfig"},
                "condition": {"type": "absolute_value"},
                "calculation_interval": AlertCalculationInterval.DAILY,
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 5}}},
            },
        )

    @patch("posthog.api.alert.posthoganalytics.feature_enabled", return_value=True)
    def test_creates_hogql_alert_when_flag_on(self, _mock_feature_enabled: MagicMock) -> None:
        insight = self._create_hogql_insight()
        response = self._post_alert(insight["id"])
        assert response.status_code == 201, response.content

    @patch("posthog.api.alert.posthoganalytics.feature_enabled", return_value=False)
    def test_rejects_hogql_alert_when_flag_off(self, _mock_feature_enabled: MagicMock) -> None:
        insight = self._create_hogql_insight()
        response = self._post_alert(insight["id"])
        assert response.status_code == 400
        assert "SQL insight alerts are not enabled" in response.content.decode()

    @patch("posthog.api.alert.posthoganalytics.feature_enabled", return_value=True)
    def test_rejects_unsupported_query_kind(self, _mock_feature_enabled: MagicMock) -> None:
        funnels_query = {
            "kind": "FunnelsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
        }
        insight = self.dashboard_api.create_insight(data={"name": "funnel", "query": funnels_query})[1]
        response = self._post_alert(insight["id"])
        assert response.status_code == 400
