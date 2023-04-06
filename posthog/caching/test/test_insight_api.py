from datetime import datetime, timedelta
from django.http import HttpRequest

import pytz
from freezegun import freeze_time
from rest_framework.request import Request
from posthog.caching.insight_caching_state import InsightCachingState
from posthog.caching.insights_api import BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL, should_refresh_insight
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_insight


@freeze_time("2012-01-14T03:21:34.000Z")
class TestInsightAPI(ClickhouseTestMixin, BaseTest):
    def test_should_refresh_now_should_always_be_true_if_the_insight_doesnt_have_last_refresh(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {})
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    def test_dashboard_filters_should_override_insight_filters_when_deciding_on_refresh_time(self):
        insight, _, dashboard_tile = _create_insight(
            self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {"interval": "hour"}
        )
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, dashboard_tile, request=Request(request)
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

    def test_insights_with_hour_intervals_can_be_refreshed_more_often(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "hour"}, {})
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # TRICKY: Shared insights cannot be refreshed more often
        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=Request(request), is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=15))

    def test_insights_with_ranges_lower_than_7_days_can_be_refreshed_more_often(self):
        insight, _, _ = _create_insight(
            self.team, {"events": [{"id": "$pageview"}], "interval": "day", "date_from": "-3d"}, {}
        )
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # TRICKY: Shared insights cannot be refreshed more often
        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=Request(request), is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=15))

    def test_insights_recently_refreshed_should_return_false_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC"))
        )
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))

        self.assertEqual(should_refresh_now, False)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    def test_insights_without_refresh_requested_should_return_false_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1)
        )
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))

        self.assertEqual(should_refresh_now, False)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    def test_insights_with_refresh_requested_should_return_true_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1)
        )
        request = HttpRequest()
        request.GET["refresh"] = "true"

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None, request=Request(request))

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL)

    def test_shared_insights_without_refresh_requested_should_return_true_for_should_refresh_now(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1)
        )
        request = HttpRequest()

        should_refresh_now, refresh_frequency = should_refresh_insight(
            insight, None, request=Request(request), is_shared=True
        )

        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=30))  # This interval is increased

    def test_shared_insights_without_refresh_requested_should_return_false_for_should_refresh_now_if_refreshing(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1),
            # This insight is being calculated _somewhere_, since it was last refreshed
            # earlier than the recent refresh has been queued
            last_refresh_queued_at=datetime.now(tz=pytz.timezone("UTC")) - timedelta(seconds=1),
        )
        request = HttpRequest()

        should_refresh_now, _ = should_refresh_insight(insight, None, request=Request(request), is_shared=True)

        self.assertEqual(should_refresh_now, False)

    def test_shared_insights_without_refresh_requested_should_return_true_for_should_refresh_now_if_failed(self):
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC")) - timedelta(days=1),
            # last_refresh is earlier than last_refresh_queued_at BUT last_refresh_queued_at is more than
            # CLICKHOUSE_MAX_EXECUTION_TIME seconds ago. This means the query CANNOT be running at this time.
            last_refresh_queued_at=datetime.now(tz=pytz.timezone("UTC")) - timedelta(seconds=500),
        )
        request = HttpRequest()

        should_refresh_now, _ = should_refresh_insight(insight, None, request=Request(request), is_shared=True)

        self.assertEqual(should_refresh_now, True)
