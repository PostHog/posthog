from datetime import datetime, timedelta

import pytz
from freezegun import freeze_time

from posthog.caching.insight_caching_state import InsightCachingState
from posthog.caching.insights_api import DEFAULT_CLIENT_INSIGHT_ALLOWED_REFRESH_FREQUENCY, should_refresh_insight
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_insight


@freeze_time("2012-01-14T03:21:34.000Z")
class TestInsightAPI(ClickhouseTestMixin, BaseTest):
    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_refresh_insight(self) -> None:
        # should_refresh_now should always be true if the insight doesn't have last_refresh
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {})
        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None)
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, DEFAULT_CLIENT_INSIGHT_ALLOWED_REFRESH_FREQUENCY)

        # dashboard filters override insight filters when deciding on refresh time
        insight, _, dashboard_tile = _create_insight(
            self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {"interval": "hour"}
        )
        should_refresh_now, refresh_frequency = should_refresh_insight(insight, dashboard_tile)
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # insights with hour intervals can be refreshed more often
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "hour"}, {})

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None)
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # insight with ranges equal or lower than 7 days can also be refreshed more often
        insight, _, _ = _create_insight(
            self.team, {"events": [{"id": "$pageview"}], "interval": "day", "date_from": "-3d"}, {}
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None)
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, timedelta(minutes=3))

        # insights recently refreshed should return False for should_refresh_now
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$autocapture"}], "interval": "month"}, {})
        InsightCachingState.objects.filter(team=self.team, insight_id=insight.pk).update(
            last_refresh=datetime.now(tz=pytz.timezone("UTC"))
        )

        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None)
        self.assertEqual(should_refresh_now, False)
        self.assertEqual(refresh_frequency, DEFAULT_CLIENT_INSIGHT_ALLOWED_REFRESH_FREQUENCY)
