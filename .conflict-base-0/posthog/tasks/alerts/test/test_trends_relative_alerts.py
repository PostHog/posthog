from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseDestroyTablesMixin, _create_event, flush_persons_and_events
from unittest.mock import ANY, MagicMock, call, patch

import pytz
import dateutil
import dateutil.relativedelta

from posthog.schema import (
    AlertCalculationInterval,
    AlertConditionType,
    AlertState,
    BaseMathType,
    Breakdown,
    BreakdownFilter,
    ChartDisplayType,
    DateRange,
    EventsNode,
    InsightThresholdType,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.alerts.checks import check_alert

# Tuesday
FROZEN_TIME = dateutil.parser.parse("2024-06-04T08:55:00.000Z")


@freeze_time(FROZEN_TIME)
@patch("posthog.tasks.alerts.checks.send_notifications_for_errors")
@patch("posthog.tasks.alerts.checks.send_notifications_for_breaches")
class TestTimeSeriesTrendsRelativeAlerts(APIBaseTest, ClickhouseDestroyTablesMixin):
    def setUp(self) -> None:
        super().setUp()

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def create_alert(
        self,
        insight: dict,
        series_index: int,
        condition_type: AlertConditionType,
        threshold_type: InsightThresholdType,
        lower: Optional[float] = None,
        upper: Optional[float] = None,
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
                "condition": {"type": condition_type},
                "calculation_interval": AlertCalculationInterval.DAILY,
                "threshold": {"configuration": {"type": threshold_type, "bounds": {"lower": lower, "upper": upper}}},
            },
        ).json()

        return alert

    def create_time_series_trend_insight(
        self,
        interval: IntervalType,
        breakdown: Optional[BreakdownFilter] = None,
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

    def test_alert_properties(self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)
        # alert if sign ups increase by less than 1
        alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            lower=1,
        )

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
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 0
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

    def test_relative_increase_absolute_upper_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by more than 1
        alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)
        # Previous to previous interval (last to last week) has 0 events
        # add events for previous interval (last week on Sat)
        last_sat = FROZEN_TIME - dateutil.relativedelta.relativedelta(days=3)
        with freeze_time(last_sat):
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
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (2) increased more than upper threshold (1.0)"]
        )

    def test_relative_increase_upper_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups increase by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

    def test_relative_increase_lower_threshold_breached_1(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by less than 2
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            lower=2,
        )

        # alert if sign ups increase by less than 20
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            lower=0.5,  # 50%
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 2 events
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
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

        # set previous interval to have 1 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as overall we had *decrease* in events (-1 or -50%) week over week
        # check absolute alert
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == -1
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (-1) increased less than lower threshold (2.0)"]
        )

        # check percentage alert
        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == -0.5  # 50% decrease
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_with(
            ANY,
            ["The insight value (signed_up) for previous week (-50.00%) increased less than lower threshold (50.00%)"],
        )

    def test_relative_increase_lower_threshold_breached_2(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by less than 2
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            lower=2,
        )

        # alert if sign ups increase by less than 110%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            lower=1.1,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as overall we had *increase* in events of just (1 or 100%) week over week
        # alert required at least 2
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 1
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 1
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

    def test_relative_decrease_upper_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups decrease by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups decrease by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 3 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
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
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 1 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had decrease in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (2) decreased more than upper threshold (1.0)"]
        )

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == (2 / 3)
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_with(
            ANY,
            ["The insight value (signed_up) for previous week (66.67%) decreased more than upper threshold (20.00%)"],
        )

    def test_relative_decrease_lower_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups decrease by less than 2
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            lower=2,
        )

        # alert if sign ups decrease by less than 80%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            lower=0.8,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 2 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
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

        # set previous interval to have 1 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had decrease in events of (1 or 50%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 1
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (1) decreased less than lower threshold (2.0)"]
        )

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 0.5
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_with(
            ANY,
            ["The insight value (signed_up) for previous week (50.00%) decreased less than lower threshold (80.00%)"],
        )

    def test_relative_increase_no_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by more than 4
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=4,
        )

        # alert if sign ups increase by more than 400%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=4,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 3 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
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
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert shouldn't fire as increase was only of 2 or 200%
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

    def test_relative_decrease_no_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by more than 4
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=4,
        )

        # alert if sign ups decrease by more than 80%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.8,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 3 events
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 1 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert shouldn't fire as increase was only of 2 or 200%
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")
        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")
        assert alert_check.calculated_value == (2 / 3)
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

    def test_breakdown_relative_increase_upper_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(
            interval=IntervalType.WEEK, breakdown=BreakdownFilter(breakdowns=[Breakdown(property="$browser")])
        )

        # alert if sign ups increase by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups increase by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
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
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_has_calls(
            [
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Chrome) for previous week (2.0) increased more than upper threshold (1.0)"
                    ],
                ),
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Chrome) for previous week (200.00%) increased more than upper threshold (20.00%)"
                    ],
                ),
            ]
        )

    def test_breakdown_relative_increase_lower_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(
            interval=IntervalType.WEEK, breakdown=BreakdownFilter(breakdowns=[Breakdown(property="$browser")])
        )

        # alert if sign ups don't increase by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            lower=1,
        )

        # alert if sign ups don't increase by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            lower=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
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
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 0
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 0
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_has_calls(
            [
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Firefox) for previous week (0.0) increased less than lower threshold (1.0)"
                    ],
                ),
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Firefox) for previous week (0.00%) increased less than lower threshold (20.00%)"
                    ],
                ),
            ]
        )

    def test_breakdown_relative_decrease_lower_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(
            interval=IntervalType.WEEK, breakdown=BreakdownFilter(breakdowns=[Breakdown(property="$browser")])
        )

        # alert if sign ups decrease by less than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            lower=1,
        )

        # alert if sign ups decrease by less than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            lower=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
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
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == -2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == -2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_has_calls(
            [
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Chrome) for previous week (-2.0) decreased less than lower threshold (1.0)"
                    ],
                ),
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Chrome) for previous week (-200.00%) decreased less than lower threshold (20.00%)"
                    ],
                ),
            ]
        )

    def test_breakdown_relative_decrease_upper_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(
            interval=IntervalType.WEEK, breakdown=BreakdownFilter(breakdowns=[Breakdown(property="$browser")])
        )

        # alert if sign ups decrease by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups decrease by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
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
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )

            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == (2 / 3)
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_has_calls(
            [
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Chrome) for previous week (2.0) decreased more than upper threshold (1.0)"
                    ],
                ),
                call(
                    ANY,
                    [
                        "The insight value (signed_up - Chrome) for previous week (66.67%) decreased more than upper threshold (20.00%)"
                    ],
                ),
            ]
        )

    def test_breakdown_relative_decrease_no_breaches(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(
            interval=IntervalType.WEEK, breakdown=BreakdownFilter(breakdowns=[Breakdown(property="$browser")])
        )

        # alert if sign ups decrease by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups decrease by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )

            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value is None
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value is None
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_not_called()

    def test_breakdown_relative_increase_no_breaches(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(
            interval=IntervalType.WEEK, breakdown=BreakdownFilter(breakdowns=[Breakdown(property="$browser")])
        )

        # alert if sign ups decrease by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups decrease by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous to previous interval (last to last week) to have 1 event
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval to have 2 event
        # add events for last week (last Tue)
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)
        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="11",
                properties={"$browser": "Firefox"},
            )

            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value is None
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value is None
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_not_called()

    def test_current_interval_relative_increase_upper_threshold_breached(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
            check_ongoing_interval=True,
        )

        # alert if sign ups increase by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
            check_ongoing_interval=True,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set current interval to have 3 events
        with freeze_time(FROZEN_TIME):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval (last week) to have 1 event
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)

        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous to previous interval (last to last week) to also have 1 event
        # so event shouldn't fire for the previous week
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for current week (2) increased more than upper threshold (1.0)"]
        )

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_with(
            ANY,
            ["The insight value (signed_up) for current week (200.00%) increased more than upper threshold (20.00%)"],
        )

    def test_current_interval_relative_increase_does_not_fallback_to_previous_interval(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
            check_ongoing_interval=True,
        )

        # alert if sign ups increase by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
            check_ongoing_interval=True,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set current interval to have 1 events
        with freeze_time(FROZEN_TIME):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="2",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous interval (last week) to have 3 events
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)

        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="4",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous to previous interval (last to last week) to also have 1 event
        # so event shouldn't fire for the previous week
        last_to_last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=2)

        with freeze_time(last_to_last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # alert should fire as we had *increase* in events of (2 or 200%) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        # decrease of 2 events compared to week before
        # shouln't look a previous interval which had increase of 2
        assert alert_check.calculated_value == -2
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == -2 / 3
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

    def test_relative_increase_when_previous_value_is_0(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups increase by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups increase by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_INCREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous interval (last week) to have 2 events
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)

        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous to previous interval (last to last week) to have 0 events

        # alert should fire as we had *increase* in events of (infinity) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == 2
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        # should be 'previous' week as we haven't breached for current week
        # so logic fallback to previous week
        mock_send_breaches.assert_called_once_with(
            ANY, ["The insight value (signed_up) for previous week (2) increased more than upper threshold (1.0)"]
        )

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == float("inf")
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_with(
            ANY,
            ["The insight value (signed_up) for previous week (inf%) increased more than upper threshold (20.00%)"],
        )

    def test_relative_decrease_when_previous_value_is_0(
        self, mock_send_breaches: MagicMock, mock_send_errors: MagicMock
    ) -> None:
        insight = self.create_time_series_trend_insight(interval=IntervalType.WEEK)

        # alert if sign ups decreases by more than 1
        absolute_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.ABSOLUTE,
            upper=1,
        )

        # alert if sign ups decreases by more than 20%
        percentage_alert = self.create_alert(
            insight,
            series_index=0,
            condition_type=AlertConditionType.RELATIVE_DECREASE,
            threshold_type=InsightThresholdType.PERCENTAGE,
            upper=0.2,
        )

        # FROZEN_TIME is on Tue, insight has weekly interval
        # we aggregate our weekly insight numbers to display for Sun (19th May, 26th May, 2nd June)

        # set previous interval (last week) to have 2 events
        last_tue = FROZEN_TIME - dateutil.relativedelta.relativedelta(weeks=1)

        with freeze_time(last_tue):
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="1",
                properties={"$browser": "Chrome"},
            )
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="3",
                properties={"$browser": "Chrome"},
            )
            flush_persons_and_events()

        # set previous to previous interval (last to last week) to have 0 events

        # alert should fire as we had *decrease* in events of (infinity) week over week
        check_alert(absolute_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=absolute_alert["id"])
        assert updated_alert.state == AlertState.NOT_FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=absolute_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == -2
        assert alert_check.state == AlertState.NOT_FIRING
        assert alert_check.error is None

        check_alert(percentage_alert["id"])

        updated_alert = AlertConfiguration.objects.get(pk=percentage_alert["id"])
        assert updated_alert.state == AlertState.FIRING

        next_check = (FROZEN_TIME + dateutil.relativedelta.relativedelta(days=1)).replace(hour=1, tzinfo=pytz.UTC)
        assert updated_alert.next_check_at
        assert updated_alert.next_check_at.hour == next_check.hour
        assert updated_alert.next_check_at.date() == next_check.date()

        alert_check = AlertCheck.objects.filter(alert_configuration=percentage_alert["id"]).latest("created_at")

        assert alert_check.calculated_value == float("inf")
        assert alert_check.state == AlertState.FIRING
        assert alert_check.error is None

        mock_send_breaches.assert_called_with(
            ANY,
            ["The insight value (signed_up) for previous week (inf%) decreased more than upper threshold (20.00%)"],
        )
