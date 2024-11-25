from typing import Optional, Any
from unittest.mock import ANY, MagicMock, patch
import dateutil

from freezegun import freeze_time

from posthog.models.alert import AlertCheck
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.checks import check_alert
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events, ClickhouseDestroyTablesMixin
from posthog.api.test.dashboards import DashboardAPI
from posthog.schema import (
    ChartDisplayType,
    EventsNode,
    TrendsQuery,
    TrendsFilter,
    IntervalType,
    InsightDateRange,
    BaseMathType,
    AlertState,
    AlertCalculationInterval,
    BreakdownFilter,
    Breakdown,
)
from posthog.models import AlertConfiguration

FROZEN_TIME = dateutil.parser.parse("2024-06-02T08:55:00.000Z")


@freeze_time(FROZEN_TIME)
@patch("posthog.tasks.alerts.checks.send_notifications_for_errors")
@patch("posthog.tasks.alerts.checks.send_notifications_for_breaches")
class TestTimeSeriesTrendsAbsoluteAlerts(APIBaseTest, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def create_alert(
        self, insight: dict, series_index: int, lower: Optional[int] = None, upper: Optional[int] = None
    ) -> dict:
        alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": insight["id"],
                "subscribed_users": [self.user.id],
                "config": {
                    "type": "TrendsAlertConfig",
                    "series_index": series_index,
                },
                "condition": {"type": "absolute_value"},
                "calculation_interval": AlertCalculationInterval.DAILY,
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": lower, "upper": upper}}},
            },
        ).json()

        return alert

    def create_time_series_trend_insight(self, breakdown: Optional[BreakdownFilter] = None) -> dict[str, Any]:
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="signed_up",
                    math=BaseMathType.TOTAL,
                ),
                EventsNode(
                    event="$pageview",
                    name="Pageview",
                    math=BaseMathType.TOTAL,
                ),
            ],
            breakdownFilter=breakdown,
            trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            interval=IntervalType.WEEK,
            dateRange=InsightDateRange(date_from="-8w"),
        ).model_dump()

        insight = self.dashboard_api.create_insight(
            data={
                "name": "insight",
                "query": query_dict,
            }
        )[1]

        return insight

    def create_aggregate_trend_insight(self, breakdown: Optional[BreakdownFilter] = None) -> dict[str, Any]:
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="signed_up",
                    math=BaseMathType.TOTAL,
                ),
                EventsNode(
                    event="$pageview",
                    name="Pageview",
                    math=BaseMathType.TOTAL,
                ),
            ],
            breakdownFilter=breakdown,
            trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_PIE),
            interval=IntervalType.WEEK,
            dateRange=InsightDateRange(date_from="-8w"),
        ).model_dump()

        insight = self.dashboard_api.create_insight(
            data={
                "name": "insight",
                "query": query_dict,
            }
        )[1]

        return insight

    def test_alert_lower_threshold_breached(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock) -> None:
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(insight, series_index=0, lower=1)

        assert alert["state"] == AlertState.NOT_FIRING
        assert alert["last_checked_at"] is None
        assert alert["last_notified_at"] is None
        assert alert["next_check_at"] is None

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        assert updated_alert.last_checked_at == FROZEN_TIME
        assert updated_alert.last_notified_at == FROZEN_TIME
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 0
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (0) is less than lower threshold (1.0)"]
        )

    def test_trend_high_threshold_breached(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock) -> None:
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(insight, series_index=0, upper=1)

        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(days=1)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (2) is more than upper threshold (1.0)"]
        )

    def test_trend_no_threshold_breached(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock) -> None:
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(insight, series_index=0, lower=0, upper=2)

        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(days=1)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 1
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

    def test_trend_breakdown_high_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(BreakdownFilter(breakdowns=[Breakdown(property="$browser")]))
        alert = self.create_alert(insight, series_index=0, upper=1)

        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(days=1)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up - Chrome) for previous week (2.0) is more than upper threshold (1.0)"]
        )

    def test_trend_breakdown_low_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(BreakdownFilter(breakdowns=[Breakdown(property="$browser")]))
        alert = self.create_alert(insight, series_index=0, lower=2)

        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(days=1)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 1
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up - Firefox) for previous week (1.0) is less than lower threshold (2.0)"]
        )

    def test_trend_breakdown_no_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(BreakdownFilter(breakdowns=[Breakdown(property="$browser")]))
        alert = self.create_alert(insight, series_index=0, lower=1)

        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(days=1)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value is None
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_not_called()

    def test_aggregate_trend_high_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_aggregate_trend_insight()
        alert = self.create_alert(insight, series_index=0, upper=1)

        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=4)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 3
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous interval (3) is more than upper threshold (1.0)"]
        )

    def test_aggregate_trend_with_breakdown_high_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_aggregate_trend_insight(BreakdownFilter(breakdowns=[Breakdown(property="$browser")]))
        alert = self.create_alert(insight, series_index=0, upper=1)

        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=4)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up - Chrome) for previous interval (2) is more than upper threshold (1.0)"]
        )
