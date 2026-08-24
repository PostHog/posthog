from typing import Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.schema import (
    AlertState,
    ChartDisplayType,
    DateRange,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsFormulaNode,
    TrendsQuery,
)

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
        return mock_send_notifications_for_breaches.call_args_list[call_index].args[1]

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

    def test_hourly_alert_on_single_number_insight_outlives_its_cache(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        # A single-number display discards the configured interval for `day` (TrendsQueryRunner
        # .query_date_range), so this minute-interval, one-hour insight lands on day's six-hour
        # staleness window. Its check reuses the insight's own query, so both read that one cached
        # entry and an hourly check kept re-reading a number from hours earlier. The interval is
        # explicitly `minute` here to pin that the configured value does not save it: only the
        # cadence ceiling forces the recompute.
        query_dict = TrendsQuery(
            series=[EventsNode(event="$exception")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            interval=IntervalType.MINUTE,
            dateRange=DateRange(date_from="-1h"),
        ).model_dump()
        insight = self.dashboard_api.create_insight(data={"name": "errors last hour", "query": query_dict})[1]
        alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "errors last hour",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "hourly",
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"upper": 1}}},
            },
        ).json()

        # Quiet hour: this check caches a below-threshold value.
        with freeze_time("2024-06-02T08:55:00.000Z"):
            run_alert_check(alert["id"])
        assert AlertConfiguration.objects.get(pk=alert["id"]).state == AlertState.NOT_FIRING

        with freeze_time("2024-06-02T09:30:00.000Z"):
            for distinct_id in range(3):
                _create_event(team=self.team, event="$exception", distinct_id=str(distinct_id))
            flush_persons_and_events()

        # 59 minutes on, which is how far apart consecutive hourly checks actually land: each is
        # scheduled from the previous one's due time and the check itself takes a moment, so the gap
        # is always a shade under the cadence. A ceiling of one whole cadence would serve the cached
        # zero here and leave every second check stale.
        with freeze_time("2024-06-02T09:54:00.000Z"):
            run_alert_check(alert["id"])

        check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert check.calculated_value == 3
        assert check.state == AlertState.FIRING

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
