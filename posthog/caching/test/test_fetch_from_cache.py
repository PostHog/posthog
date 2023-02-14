from datetime import datetime, timedelta
from typing import Any, Dict, Tuple

import pytz
from django.utils.timezone import now
from freezegun import freeze_time

from posthog.caching.fetch_from_cache import (
    DEFAULT_INSIGHT_REFRESH_FREQUENCY,
    InsightResult,
    NothingInCacheResult,
    fetch_cached_insight_result,
    should_refresh_insight,
    synchronously_update_cache,
)
from posthog.caching.insight_caching_state import InsightCachingState
from posthog.decorators import CacheType
from posthog.models import Dashboard, DashboardTile, Insight, Team
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from posthog.utils import get_safe_cache


def _create_insight(
    team: Team, insight_filters: Dict[str, Any], dashboard_filters: Dict[str, Any]
) -> Tuple[Insight, Dashboard, DashboardTile]:
    dashboard = Dashboard.objects.create(team=team, filters=dashboard_filters)
    insight = Insight.objects.create(team=team, filters=insight_filters)
    dashboard_tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
    return insight, dashboard, dashboard_tile


@freeze_time("2012-01-14T03:21:34.000Z")
class TestFetchFromCache(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()

        _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"prop": "val"})
        _create_event(team=self.team, event="$pageview", distinct_id="2", properties={"prop": "another_val"})
        flush_persons_and_events()

        insight, dashboard, dashboard_tile = _create_insight(
            self.team, {"events": [{"id": "$pageview"}], "properties": []}, {"properties": [{}]}
        )
        self.dashboard = dashboard
        self.insight = insight
        self.dashboard_tile = dashboard_tile

    def test_synchronously_update_cache_insight(self):
        insight = Insight.objects.create(team=self.team, filters={"events": [{"id": "$pageview"}], "properties": []})

        result = synchronously_update_cache(insight, None)

        assert result.result is not None
        assert result.last_refresh == now()
        assert not result.is_cached
        assert result.cache_key is not None

        assert insight.caching_state.cache_key == result.cache_key
        assert insight.caching_state.last_refresh == result.last_refresh

        cached_result = get_safe_cache(result.cache_key)
        assert cached_result == {
            "result": result.result,
            "type": CacheType.TRENDS,
            "last_refresh": result.last_refresh,
            "next_allowed_refresh": None,
        }

    def test_synchronously_update_cache_dashboard_tile(self):
        result = synchronously_update_cache(self.insight, self.dashboard)

        assert result.result is not None
        assert result.last_refresh == now()
        assert not result.is_cached
        assert result.cache_key is not None

        assert self.insight.caching_state.cache_key != result.cache_key
        assert self.dashboard_tile.caching_state.cache_key == result.cache_key
        assert self.dashboard_tile.caching_state.last_refresh == result.last_refresh

        cached_result = get_safe_cache(result.cache_key)
        assert cached_result == {
            "result": result.result,
            "type": CacheType.TRENDS,
            "last_refresh": result.last_refresh,
            "next_allowed_refresh": None,
        }

    def test_fetch_cached_insight_result_from_cache(self):
        cached_result = synchronously_update_cache(self.insight, self.dashboard, timedelta(minutes=3))
        from_cache_result = fetch_cached_insight_result(self.dashboard_tile, timedelta(minutes=3))

        assert from_cache_result == InsightResult(
            result=cached_result.result,
            last_refresh=cached_result.last_refresh,
            cache_key=cached_result.cache_key,
            is_cached=True,
            timezone=None,
            next_allowed_refresh=cached_result.next_allowed_refresh,
        )

    def test_fetch_nothing_yet_cached(self):
        from_cache_result = fetch_cached_insight_result(self.dashboard_tile, timedelta(minutes=3))

        assert isinstance(from_cache_result, NothingInCacheResult)
        assert from_cache_result.result is None
        assert from_cache_result.cache_key is not None

    def test_fetch_invalid_filter(self):
        self.insight.filters = {}
        self.insight.save()

        from_cache_result = fetch_cached_insight_result(self.insight, timedelta(minutes=3))

        assert isinstance(from_cache_result, NothingInCacheResult)
        assert from_cache_result.result is None
        assert from_cache_result.cache_key is None

    @freeze_time("2012-01-14T03:21:34.000Z")
    def test_should_refresh_insight(self) -> None:
        # should_refresh_now should always be true if the insight doesn't have last_refresh
        insight, _, _ = _create_insight(self.team, {"events": [{"id": "$pageview"}], "interval": "month"}, {})
        should_refresh_now, refresh_frequency = should_refresh_insight(insight, None)
        self.assertEqual(should_refresh_now, True)
        self.assertEqual(refresh_frequency, DEFAULT_INSIGHT_REFRESH_FREQUENCY)

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
        self.assertEqual(refresh_frequency, DEFAULT_INSIGHT_REFRESH_FREQUENCY)
