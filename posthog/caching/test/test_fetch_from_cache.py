from django.utils.timezone import now
from freezegun import freeze_time

from posthog.caching.fetch_from_cache import (
    InsightResult,
    NothingInCacheResult,
    fetch_cached_insight_result,
    synchronously_update_cache,
)
from posthog.decorators import CacheType
from posthog.models import Dashboard, DashboardTile, Insight
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from posthog.utils import get_safe_cache


@freeze_time("2012-01-14T03:21:34.000Z")
class TestFetchFromCache(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()

        _create_event(team=self.team, event="$pageview", distinct_id="1", properties={"prop": "val"})
        _create_event(team=self.team, event="$pageview", distinct_id="2", properties={"prop": "another_val"})
        flush_persons_and_events()

        self.dashboard = Dashboard.objects.create(team=self.team, filters={"properties": [{}]})
        self.insight = Insight.objects.create(
            team=self.team, filters={"events": [{"id": "$pageview"}], "properties": []}
        )
        self.dashboard_tile = DashboardTile.objects.create(dashboard=self.dashboard, insight=self.insight)

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
        assert cached_result == {"result": result.result, "type": CacheType.TRENDS, "last_refresh": result.last_refresh}

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
        assert cached_result == {"result": result.result, "type": CacheType.TRENDS, "last_refresh": result.last_refresh}

    def test_fetch_cached_insight_result_from_cache(self):
        cached_result = synchronously_update_cache(self.insight, self.dashboard)
        from_cache_result = fetch_cached_insight_result(self.dashboard_tile)

        assert from_cache_result == InsightResult(
            result=cached_result.result,
            last_refresh=cached_result.last_refresh,
            cache_key=cached_result.cache_key,
            is_cached=True,
            timezone=None,
        )

    def test_fetch_nothing_yet_cached(self):
        from_cache_result = fetch_cached_insight_result(self.dashboard_tile)

        assert isinstance(from_cache_result, NothingInCacheResult)
        assert from_cache_result.result is None
        assert from_cache_result.cache_key is not None

    def test_fetch_invalid_filter(self):
        self.insight.filters = {}
        self.insight.save()

        from_cache_result = fetch_cached_insight_result(self.insight)

        assert isinstance(from_cache_result, NothingInCacheResult)
        assert from_cache_result.result is None
        assert from_cache_result.cache_key is None
