from datetime import timedelta

from django.utils.timezone import now
from freezegun import freeze_time

from posthog.caching.fetch_from_cache import (
    InsightResult,
    NothingInCacheResult,
    fetch_cached_insight_result,
    synchronously_update_cache,
)
from posthog.decorators import CacheType
from posthog.models import Insight
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_insight,
    flush_persons_and_events,
)
from posthog.utils import get_safe_cache


@freeze_time("2012-01-14T03:21:34.000Z")
class TestFetchFromCache(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()

        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="1",
            properties={"prop": "val"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="2",
            properties={"prop": "another_val"},
        )
        flush_persons_and_events()

        insight, dashboard, dashboard_tile = _create_insight(
            self.team,
            {"events": [{"id": "$pageview"}], "properties": []},
            {"properties": [{}]},
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
            "next_allowed_client_refresh": None,
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
            "next_allowed_client_refresh": None,
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
            next_allowed_client_refresh=cached_result.next_allowed_client_refresh,
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
