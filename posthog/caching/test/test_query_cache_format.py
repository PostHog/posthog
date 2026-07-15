from posthog.test.base import BaseTest

from django.test import override_settings

from posthog.caching.fetch_from_cache import fetch_cached_response_by_key, fetch_split_cached_response_by_key
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager


class TestQueryCacheWriteFormat(BaseTest):
    def test_writes_legacy_format_until_split_writes_enabled(self):
        # Old readers treat split-format entries as cache misses and recompute, so shipping
        # split writes before every reader understands the format causes a cache-load spike
        # on deploy. Split writes must stay opt-in via QUERY_CACHE_SPLIT_FORMAT_WRITES.
        response = {"is_cached": False, "results": [{"data": [1]}], "cache_key": "k"}
        manager = get_query_cache_manager(team=self.team, cache_key=f"cache_format_test_{self.team.pk}", insight_id=1)

        manager.set_cache_data(response=response, target_age=None)
        split = fetch_split_cached_response_by_key(manager.cache_key, self.team.pk)
        assert split is not None
        assert split.results_bytes is None
        assert split.header["results"] == [{"data": [1]}]

        with override_settings(QUERY_CACHE_SPLIT_FORMAT_WRITES=True):
            manager.set_cache_data(response=response, target_age=None)
        split = fetch_split_cached_response_by_key(manager.cache_key, self.team.pk)
        assert split is not None
        assert split.results_bytes == b'[{"data":[1]}]'
        assert fetch_cached_response_by_key(manager.cache_key, self.team.pk) == {
            "is_cached": False,
            "results": [{"data": [1]}],
            "cache_key": "k",
        }
