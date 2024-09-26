from typing import Optional
from unittest.mock import MagicMock, patch
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
    EventPropertyFilter,
    PropertyOperator,
    BaseMathType,
    AlertState,
    AlertCalculationInterval,
    BreakdownFilter,
)
from posthog.models import AlertConfiguration

FROZEN_TIME = dateutil.parser.parse("2024-06-02T08:55:00.000Z")


@freeze_time("2024-06-02T08:55:00.000Z")
@patch("posthog.tasks.alerts.checks._send_notifications_for_errors")
@patch("posthog.tasks.alerts.checks._send_notifications_for_breaches")
class TestTimeSeriesTrendsAlerts(APIBaseTest, ClickhouseDestroyTablesMixin):
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
                "calculation_interval": AlertCalculationInterval.DAILY,
                "threshold": {"configuration": {"absoluteThreshold": {"lower": lower, "upper": upper}}},
            },
        ).json()

        return alert

    def create_time_series_trend_insight(self, breakdown: Optional[BreakdownFilter] = None):
        query_dict = TrendsQuery(
            series=[
                EventsNode(
                    event="signed_up",
                    math=BaseMathType.TOTAL,
                    properties=[
                        EventPropertyFilter(
                            key="$browser",
                            operator=PropertyOperator.EXACT,
                            value=["Chrome"],
                        )
                    ],
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

    def test_alert_properties(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock):
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

    def test_trend_high_threshold_breached(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock):
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(insight, series_index=0, upper=1)

        with freeze_time("2024-06-02T07:55:00.000Z"):
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

    def test_trend_no_threshold_breached(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock):
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(insight, series_index=0, lower=0, upper=2)

        with freeze_time("2024-06-02T07:55:00.000Z"):
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

    # TODO: support breakdowns
    def test_trend_with_single_breakdown_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ):
        insight = self.create_time_series_trend_insight(
            breakdown=BreakdownFilter(breakdown_type="event", breakdown="$browser")
        )
        alert = self.create_alert(insight, series_index=0, lower=0, upper=1)

        with freeze_time("2024-06-02T07:55:00.000Z"):
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
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Firefox"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING
        assert updated_alert.next_check_at == FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        # calculated value should only be from browser = Chrome
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None
