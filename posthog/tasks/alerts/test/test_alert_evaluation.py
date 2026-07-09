from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.schema import AlertState, ChartDisplayType, EventsNode, TrendsFilter, TrendsFormulaNode, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.test.alert_check_helpers import run_alert_check

from products.alerts.backend.models import AlertCheck, AlertConfiguration


@freeze_time("2024-06-02T08:55:00.000Z")
@patch("posthog.tasks.alerts.utils.send_notifications_for_errors", return_value=[])
@patch("posthog.tasks.alerts.utils.send_notifications_for_breaches", return_value=[])
class TestAlertEvaluation(APIBaseTest, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()

        self.insight = self.dashboard_api.create_insight(data={"name": "insight", "query": query_dict})[1]

        self.alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 0}}},
            },
        ).json()

    def set_thresholds(self, lower: Optional[int] = None, upper: Optional[int] = None) -> None:
        self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{self.alert['id']}",
            data={"threshold": {"configuration": {"type": "absolute", "bounds": {"lower": lower, "upper": upper}}}},
        )

    def get_breach_description(self, mock_send_notifications_for_breaches: MagicMock, call_index: int) -> list[str]:
        return mock_send_notifications_for_breaches.call_args_list[call_index].args[2]

    def _create_formula_alert(self, query_dict: dict, series_index: int = 0) -> dict:
        insight = self.dashboard_api.create_insight(data={"name": "formula insight", "query": query_dict})[1]
        return self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "formula alert",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": series_index},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 1}}},
            },
        ).json()

    def test_alert_is_set_to_not_firing_when_threshold_changes(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        self.set_thresholds(lower=1)

        run_alert_check(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert (
            AlertCheck.objects.filter(alert_configuration=self.alert["id"]).latest("created_at").state
            == AlertState.FIRING
        )

        self.set_thresholds(lower=2)

        assert AlertConfiguration.objects.get(pk=self.alert["id"]).state == AlertState.NOT_FIRING

    def test_alert_with_insight_with_filter(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.dashboard_api.create_insight(
            data={"name": "insight", "filters": {"events": [{"id": "$pageview"}], "display": "BoldNumber"}}
        )[1]

        self.client.patch(f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"insight": insight["id"]})
        self.set_thresholds(lower=1)

        run_alert_check(self.alert["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert "The insight value ($pageview) for current interval (0) is less than lower threshold (1)" in anomalies

    def test_alert_triggered_for_single_formula(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview", custom_name="A")],
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.BOLD_NUMBER,
                formulaNodes=[TrendsFormulaNode(formula="A*2", custom_name="Double Pageviews")],
            ),
        ).model_dump()
        alert_data = self._create_formula_alert(query_dict, series_index=0)

        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            flush_persons_and_events()

        run_alert_check(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        assert str(mock_send_notifications_for_breaches.call_args_list[0].args[0].id) == alert_data["id"]
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies) == 1
        assert (
            "The insight value (Double Pageviews) for current interval (2) is more than upper threshold (1)"
            in anomalies[0]
        )

    def test_alert_triggered_for_legacy_formulas(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview", custom_name="A")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER, formulas=["A*2"]),
        ).model_dump()
        alert_data = self._create_formula_alert(query_dict, series_index=0)

        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            flush_persons_and_events()

        run_alert_check(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies) == 1
        assert (
            "The insight value (Formula (A*2)) for current interval (2) is more than upper threshold (1)"
            in anomalies[0]
        )

    def test_alert_triggered_for_legacy_formula(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview", custom_name="A")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER, formula="A*2"),
        ).model_dump()
        alert_data = self._create_formula_alert(query_dict, series_index=0)

        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            flush_persons_and_events()

        run_alert_check(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies) == 1
        assert (
            "The insight value (Formula (A*2)) for current interval (2) is more than upper threshold (1)"
            in anomalies[0]
        )

    def test_alert_triggered_for_second_formula(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview", custom_name="A")],
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.BOLD_NUMBER,
                formulaNodes=[
                    TrendsFormulaNode(formula="A", custom_name="Raw Pageviews"),
                    TrendsFormulaNode(formula="A*2", custom_name="Double Pageviews"),
                ],
            ),
        ).model_dump()
        alert_data = self._create_formula_alert(query_dict, series_index=1)

        with freeze_time("2024-06-02T07:55:00.000Z"):
            _create_event(team=self.team, event="$pageview", distinct_id="1")
            flush_persons_and_events()

        run_alert_check(alert_data["id"])

        assert mock_send_notifications_for_breaches.call_count == 1
        anomalies = self.get_breach_description(mock_send_notifications_for_breaches, call_index=0)
        assert len(anomalies) == 1
        assert (
            "The insight value (Double Pageviews) for current interval (2) is more than upper threshold (1)"
            in anomalies[0]
        )
