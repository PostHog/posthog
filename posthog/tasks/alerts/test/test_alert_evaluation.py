from typing import Optional

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    AlertState,
    BreakdownFilter,
    ChartDisplayType,
    EventsNode,
    TrendsFilter,
    TrendsFormulaNode,
    TrendsQuery,
)

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.test.alert_check_helpers import run_alert_check

from products.alerts.backend.models import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


@time_machine.travel("2024-06-02T08:55:00.000Z", tick=False)
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

    def test_alert_cannot_be_pointed_at_an_insight_with_no_query(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        # Only the ORM writes a query-less insight now, and an alert on one has nothing to evaluate.
        insight = Insight.objects.create(
            team=self.team,
            name="insight",
            filters={"events": [{"id": "$pageview"}], "display": "BoldNumber"},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/alerts/{self.alert['id']}", data={"insight": insight.id}
        )

        assert response.status_code == 400
        assert AlertConfiguration.objects.get(pk=self.alert["id"]).insight_id != insight.id

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

        with time_machine.travel("2024-06-02T07:55:00.000Z", tick=False):
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

    @parameterized.expand(
        [
            # (name, events as (event, day, breakdown value), breakdown, delay, expect breach, expected value)
            ("quiet_interval_is_skipped", [("b", "2024-06-02", None)], False, 0, False, None),
            ("real_zero_rate_breaches", [("b", "2024-06-01", None)], False, 0, True, 0.0),
            (
                "nonzero_rate_above_threshold",
                [("a", "2024-06-01", None), ("b", "2024-06-01", None)],
                False,
                0,
                False,
                1.0,
            ),
            ("quiet_breakdown_row_is_skipped", [("b", "2024-06-02", "x")], True, 0, False, None),
            ("quiet_delayed_interval_is_skipped", [("b", "2024-06-01", None)], False, 1, False, None),
        ]
    )
    def test_rate_formula_alert_skips_intervals_with_zero_denominator(
        self,
        mock_send_notifications_for_breaches: MagicMock,
        mock_send_errors: MagicMock,
        _name: str,
        events: list[tuple[str, str, Optional[str]]],
        has_breakdown: bool,
        delay: int,
        expect_breach: bool,
        expected_value: Optional[float],
    ) -> None:
        query_dict = TrendsQuery(
            series=[EventsNode(event="a"), EventsNode(event="b")],
            trendsFilter=TrendsFilter(
                display=ChartDisplayType.ACTIONS_LINE_GRAPH,
                formulaNodes=[TrendsFormulaNode(formula="A/B")],
            ),
            breakdownFilter=BreakdownFilter(breakdown="plan", breakdown_type="event") if has_breakdown else None,
        ).model_dump()
        insight = self.dashboard_api.create_insight(data={"name": "rate insight", "query": query_dict})[1]
        alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "rate alert",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": False},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 0.2}}},
                "evaluation_delay_intervals": delay,
            },
        ).json()

        for event, day, plan in events:
            _create_event(
                team=self.team,
                event=event,
                distinct_id="1",
                timestamp=f"{day}T01:00:00Z",
                properties={"plan": plan} if plan else {},
            )
        flush_persons_and_events()

        run_alert_check(alert["id"])

        check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert check.state == (AlertState.FIRING if expect_breach else AlertState.NOT_FIRING)
        assert mock_send_notifications_for_breaches.call_count == (1 if expect_breach else 0)
        assert check.calculated_value == expected_value

    def test_alert_triggered_for_legacy_formulas(
        self, mock_send_notifications_for_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview", custom_name="A")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER, formulas=["A*2"]),
        ).model_dump()
        alert_data = self._create_formula_alert(query_dict, series_index=0)

        with time_machine.travel("2024-06-02T07:55:00.000Z", tick=False):
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

        with time_machine.travel("2024-06-02T07:55:00.000Z", tick=False):
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

        with time_machine.travel("2024-06-02T07:55:00.000Z", tick=False):
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
