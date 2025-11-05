from datetime import datetime, timedelta
from time import sleep
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_insight
from unittest.mock import patch

from django.http import HttpRequest

from rest_framework.request import Request

from posthog.caching.insight_caching_state import InsightCachingState
from posthog.caching.insights_api import (
    BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL,
    CLICKHOUSE_MAX_EXECUTION_TIME,
    should_refresh_insight,
)


class TestShouldRefreshInsight(ClickhouseTestMixin, BaseTest):
    refresh_request: Request

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        django_request = HttpRequest()
        django_request.GET["refresh"] = "true"
        self.refresh_request = Request(django_request)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_return_true_if_refresh_not_requested(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=1)
        )

        # .GET["refresh"] is absent in the request below!
        should_refresh_now_none, refresh_frequency_none = should_refresh_insight(
            insight, None, request=Request(HttpRequest())
        )
        django_request = HttpRequest()
        django_request.GET["refresh"] = "false"
        should_refresh_now_false, refresh_frequency_false = should_refresh_insight(
            insight, None, request=Request(django_request)
        )

        self.assertEqual(should_refresh_now_none, False)
        self.assertEqual(refresh_frequency_none, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)
        self.assertEqual(should_refresh_now_false, False)
        self.assertEqual(refresh_frequency_false, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_return_true_if_refresh_requested(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=1)
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_return_true_if_insight_does_not_have_last_refresh(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {})

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_shared_insights_can_be_refreshed_less_often(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=1)
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=self.refresh_request, is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=30))  # This interval is increased

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_insights_with_hour_intervals_can_be_refreshed_more_often(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "hour"}, {})

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # TRICKY: Shared insights always have an increased refresh frequency
        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=self.refresh_request, is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=30))

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_insights_with_ranges_lower_than_7_days_can_be_refreshed_more_often(self):
        insight, _, _ = _create_insight(
            self.team,
            {"events": [{"id": "$pageview"}], "interval": "day", "date_from": "-3d"},
            {},
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # TRICKY: Shared insights always have an increased refresh frequency
        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=self.refresh_request, is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=30))

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_dashboard_filters_should_override_insight_filters_when_deciding_on_refresh_time(self):
        insight, _, dashboard_tile = _create_insight(
            self.team,
            {"events": [{"id": "$pageview"}], "date_from": "-30d"},
            {"date_from": "-3d"},
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, dashboard_tile, request=self.refresh_request
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_return_true_if_was_recently_refreshed(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=ZoneInfo("UTC"))
        )
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))

        self.assertEqual(should_refresh_now, False)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @patch("posthog.caching.insights_api.sleep", side_effect=sleep)
    def test_should_return_true_if_refresh_just_about_to_time_out_elsewhere(self, mock_sleep):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=1),
            # This insight is being calculated _somewhere_, since it was last refreshed
            # earlier than the recent refresh has been queued
            last_refresh_queued_at=datetime.now(tz=ZoneInfo("UTC"))
            - CLICKHOUSE_MAX_EXECUTION_TIME
            + timedelta(seconds=0.5),  # Half a second before latest possible timeout
        )

        should_refresh_now, _ = should_refresh_insight(insight, None, request=self.refresh_request)

        # We waited for 1 second before the query timed out
        mock_sleep.assert_called_once_with(1)
        # Still need to refresh, because they query didn't finish - it timed out
        self.assertEqual(should_refresh_now, True)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_return_true_if_refresh_timed_out_elsewhere_before(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=1),
            # last_refresh is earlier than last_refresh_queued_at BUT last_refresh_queued_at is more than
            # CLICKHOUSE_MAX_EXECUTION_TIME ago. This means the query CANNOT be running at this time.
            last_refresh_queued_at=datetime.now(tz=ZoneInfo("UTC")) - timedelta(seconds=500),
        )

        should_refresh_now, _ = should_refresh_insight(insight, None, request=self.refresh_request)

        self.assertEqual(should_refresh_now, True)
