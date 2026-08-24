import pickle
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.query_cache import (
    QueryCache,
    get_stale_insights,
    storage as qc_storage,
)
from posthog.query_cache.storage import entry_redis_key


class TestQueryCacheFacade(BaseTest):
    def test_writes_split_format_and_round_trips(self):
        response = {"is_cached": False, "results": [{"data": [1]}], "cache_key": "k"}
        cache = QueryCache(team_id=self.team.pk, cache_key=f"cache_format_test_{self.team.pk}", insight_id=1)

        cache.store_result(response=response, target_age=None)

        entry = cache.lookup().entry
        assert entry is not None
        assert entry.results_bytes == b'[{"data":[1]}]'
        assert entry.as_full_response() == {"is_cached": False, "results": [{"data": [1]}], "cache_key": "k"}

    def test_non_list_results_write_legacy_format(self):
        response = {"is_cached": False, "results": None, "cache_key": "k"}
        cache = QueryCache(team_id=self.team.pk, cache_key=f"cache_format_test_legacy_{self.team.pk}", insight_id=1)

        cache.store_result(response=response, target_age=None)

        entry = cache.lookup().entry
        assert entry is not None
        assert entry.results_bytes is None
        assert entry.header == response

    def test_legacy_blobs_written_before_split_rollout_stay_readable(self):
        cache_key = f"cache_format_test_preexisting_{self.team.pk}"
        response = {"is_cached": False, "results": [{"data": [1]}], "cache_key": "k"}
        # Entries from before the split format went through django_redis, which pickled them.
        legacy_value = pickle.dumps(OrjsonJsonSerializer({}).dumps(response))
        # Through the module so the fakeredis monkeypatch in conftest applies.
        qc_storage.query_cache_raw_client().set(entry_redis_key(cache_key), legacy_value, ex=60)
        cache = QueryCache(team_id=self.team.pk, cache_key=cache_key)

        entry = cache.lookup().entry
        assert entry is not None
        assert entry.results_bytes is None
        assert entry.as_full_response() == response

    def test_store_result_swallows_size_tracker_failures(self):
        cache = QueryCache(team_id=self.team.pk, cache_key=f"cache_failsoft_test_{self.team.pk}", insight_id=1)

        with patch(
            "posthog.query_cache.cache.TeamCacheSizeTracker.set",
            side_effect=OperationalError("query_wait_timeout"),
        ):
            cache.store_result(response={"results": []}, target_age=None)

        assert cache.lookup().entry is None

    def test_store_result_updates_and_clears_freshness_index(self):
        cache = QueryCache(team_id=self.team.pk, cache_key=f"cache_fresh_test_{self.team.pk}", insight_id=42)
        past = datetime.now(UTC) - timedelta(minutes=5)

        cache.store_result(response={"results": []}, target_age=past)
        assert "42:" in get_stale_insights(team_id=self.team.pk)

        cache.store_result(response={"results": []}, target_age=None)
        assert "42:" not in get_stale_insights(team_id=self.team.pk)
