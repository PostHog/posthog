from posthog.test.base import BaseTest

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.caching.fetch_from_cache import fetch_cached_response_by_key, fetch_split_cached_response_by_key
from posthog.caching.query_cache_routing import get_query_cache
from posthog.hogql_queries.query_cache_factory import get_query_cache_manager


class TestQueryCacheWriteFormat(BaseTest):
    def test_writes_split_format_and_round_trips(self):
        response = {"is_cached": False, "results": [{"data": [1]}], "cache_key": "k"}
        manager = get_query_cache_manager(team=self.team, cache_key=f"cache_format_test_{self.team.pk}", insight_id=1)

        manager.set_cache_data(response=response, target_age=None)

        split = fetch_split_cached_response_by_key(manager.cache_key, self.team.pk)
        assert split is not None
        assert split.results_bytes == b'[{"data":[1]}]'
        assert fetch_cached_response_by_key(manager.cache_key, self.team.pk) == {
            "is_cached": False,
            "results": [{"data": [1]}],
            "cache_key": "k",
        }

    def test_non_list_results_write_legacy_format(self):
        response = {"is_cached": False, "results": None, "cache_key": "k"}
        manager = get_query_cache_manager(
            team=self.team, cache_key=f"cache_format_test_legacy_{self.team.pk}", insight_id=1
        )

        manager.set_cache_data(response=response, target_age=None)

        split = fetch_split_cached_response_by_key(manager.cache_key, self.team.pk)
        assert split is not None
        assert split.results_bytes is None
        assert split.header == response

    def test_legacy_blobs_written_before_split_rollout_stay_readable(self):
        cache_key = f"cache_format_test_preexisting_{self.team.pk}"
        response = {"is_cached": False, "results": [{"data": [1]}], "cache_key": "k"}
        get_query_cache().set(cache_key, OrjsonJsonSerializer({}).dumps(response), 60)

        split = fetch_split_cached_response_by_key(cache_key, self.team.pk)
        assert split is not None
        assert split.results_bytes is None
        assert fetch_cached_response_by_key(cache_key, self.team.pk) == response
