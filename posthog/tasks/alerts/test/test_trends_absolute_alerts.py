import datetime
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import ANY, MagicMock, patch

import pytz
import dateutil

from posthog.schema import (
    AlertCalculationInterval,
    AlertState,
    BaseMathType,
    Breakdown,
    BreakdownFilter,
    ChartDisplayType,
    DateRange,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.checks import check_alert

# 8:55 AM
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
        self,
        insight: dict,
        series_index: int,
        lower: Optional[int] = None,
        upper: Optional[int] = None,
        calculation_interval: AlertCalculationInterval = AlertCalculationInterval.DAILY,
        check_ongoing_interval: bool = False,
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
                    "check_ongoing_interval": check_ongoing_interval,
                },
                "condition": {"type": "absolute_value"},
                "calculation_interval": calculation_interval,
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": lower, "upper": upper}}},
            },
        ).json()

        return alert

    def create_time_series_trend_insight(
        self,
        breakdown: Optional[BreakdownFilter] = None,
        interval: IntervalType = IntervalType.WEEK,
    ) -> dict[str, Any]:
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
            interval=interval,
            dateRange=DateRange(date_from="-8w"),
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
            dateRange=DateRange(date_from="-8w"),
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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (2) is more than upper threshold (1.0)"]
        )

    def test_trend_no_threshold_breached(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock) -> None:
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(
            insight, series_index=0, lower=0, upper=2, calculation_interval=AlertCalculationInterval.MONTHLY
        )

        with freeze_time(FROZEN_TIME):
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

        next_check = datetime.datetime(2024, 7, 1, 4, 0, tzinfo=pytz.UTC)
        # first day of next month at around 4 AM
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 0
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

    def test_trend_no_threshold_breached_weekly(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(
            insight, series_index=0, lower=0, upper=2, calculation_interval=AlertCalculationInterval.WEEKLY
        )

        with freeze_time(FROZEN_TIME):
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

        next_check = (
            FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1, weekday=dateutil.relativedelta.MO(1))
        ).replace(hour=3, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 0
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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 3
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for current interval (3) is more than upper threshold (1.0)"]
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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up - Chrome) for current interval (2) is more than upper threshold (1.0)"]
        )

    def test_trend_current_interval_high_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(insight, series_index=0, upper=1, check_ongoing_interval=True)

        # around 8 AM on same day as check
        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(hours=1)):
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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for current week (2) is more than upper threshold (1.0)"]
        )

    def test_trend_current_interval_should_not_fallback_to_previous_high_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.DAY)
        alert = self.create_alert(insight, series_index=0, upper=1, check_ongoing_interval=True)

        # current day doesn't breach
        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(hours=1)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # prev day breaches
        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(hours=26)):
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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        # has to have value for current period
        assert alert_check.calculated_value == 1
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

    def test_trend_current_interval_no_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.DAY)
        alert = self.create_alert(insight, series_index=0, upper=1)

        # day before yesterday
        with freeze_time(
            FROZEN_TIME - dateutil.relativedelta.relativedelta(days=2) - dateutil.relativedelta.relativedelta(hours=2)
        ):
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

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 0
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

    def test_trend_current_interval_low_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight()
        alert = self.create_alert(insight, series_index=0, lower=2)

        # around 8 AM on same day as check
        with freeze_time(FROZEN_TIME - dateutil.relativedelta.relativedelta(hours=1)):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        check_alert(alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at is not None
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        # will be 0 even thought for current day it's 1
        # it's because it's absolute alert and lower threshold
        # so current day isn't checked, it directly checks previous day
        assert alert_check.calculated_value == 0
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (0) is less than lower threshold (2.0)"]
        )
