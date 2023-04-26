from datetime import datetime, timedelta
from time import sleep
from unittest.mock import patch
from django.http import HttpRequest

import pytz
from freezegun import freeze_time
from rest_framework.request import Request
from posthog.caching.calculate_results import CLICKHOUSE_MAX_EXECUTION_TIME
from posthog.caching.insight_caching_state import InsightCachingState
from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, should_refresh_insight
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_insight


class TestInsightAPI(ClickhouseTestMixin, BaseTest):
    refresh_request: Request

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        django_request = HttpRequest()
        django_request.GET["refresh"] = "true"
        self.refresh_request = Request(django_request)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_refresh_now_should_always_be_true_if_the_insight_doesnt_have_last_refresh(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {})

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_dashboard_filters_should_override_insight_filters_when_deciding_on_refresh_time(self):
        insight, _, dashboard_tile = _create_insight(
            self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {"interval": "hour"}
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, dashboard_tile, request=self.refresh_request
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_insights_with_hour_intervals_can_be_refreshed_more_often(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "hour"}, {})

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # TRICKY: Shared insights cannot be refreshed more often
        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=self.refresh_request, is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=30))

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_insights_with_ranges_lower_than_7_days_can_be_refreshed_more_often(self):
        insight, _, _ = _create_insight(
            self.team, {"events": [{"id": "$pageview"}], "interval": "day", "date_from": "-3d"}, {}
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # TRICKY: Shared insights cannot be refreshed more often
        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=self.refresh_request, is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=30))

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_insights_recently_refreshed_should_return_false_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC"))
        )
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))

        self.assertEqual(should_refresh_now, False)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_insights_without_refresh_requested_should_return_false_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1)
        )

        # Note that django_request.GET["refresh"] is absent in the request below!
        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(HttpRequest()))

        self.assertEqual(should_refresh_now, False)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_insights_with_refresh_requested_should_return_true_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1)
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=self.refresh_request)

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_shared_insights_without_refresh_requested_should_return_true_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1)
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=self.refresh_request, is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=30))  # This interval is increased

    @patch("posthog.caching.insights_api.sleep", side_effect=sleep)
    def test_shared_insights_without_refresh_requested_should_return_true_for_should_refresh_now_if_refresh_timed_out(
        self, mock_sleep
    ):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1),
            # This insight is being calculated _somewhere_, since it was last refreshed
            # earlier than the recent refresh has been queued
            last_refresh_queued_at=datetime.now(tz=pytz.timezone("UTC"))
            - timedelta(seconds=CLICKHOUSE_MAX_EXECUTION_TIME - 0.5),  # Half a second before timeout
        )

        should_refresh_now, _ = should_refresh_insight(insight, None, request=self.refresh_request, is_shared=True)

        # We waited for 1 second before the query timed out
        mock_sleep.assert_called_once_with(1)
        # Still need to refresh, because they query didn't finish - it timed out
        self.assertEqual(should_refresh_now, True)

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_shared_insights_without_refresh_requested_should_return_true_for_should_refresh_now_if_failed(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1),
            # last_refresh is earlier than last_refresh_queued_at BUT last_refresh_queued_at is more than
            # CLICKHOUSE_MAX_EXECUTION_TIME seconds ago. This means the query CANNOT be running at this time.
            last_refresh_queued_at=datetime.now(tz=pytz.timezone("UTC")) - timedelta(seconds=500),
        )

        should_refresh_now, _ = should_refresh_insight(insight, None, request=self.refresh_request, is_shared=True)

        self.assertEqual(should_refresh_now, True)
