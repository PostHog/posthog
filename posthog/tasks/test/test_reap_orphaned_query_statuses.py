import datetime

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.schema import QueryStatus

from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.redis import get_client
from posthog.tasks.tasks import reap_orphaned_query_statuses


class TestReapOrphanedQueryStatuses(SimpleTestCase):
    def setUp(self) -> None:
        get_client().flushall()
        self.team_id = 4242
        self.query_id = "reaper-test-query"
        self.manager = QueryStatusManager(self.query_id, self.team_id)

    def _seed_in_progress(self, *, pickup_offset_seconds: float, complete: bool = False) -> None:
        pickup_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=pickup_offset_seconds)
        self.manager.store_query_status(
            QueryStatus(
                id=self.query_id,
                team_id=self.team_id,
                complete=complete,
                error=False,
                pickup_time=pickup_time,
            )
        )
        self.manager.add_to_in_progress_index(pickup_time.timestamp())

    def _index_members(self) -> list[str]:
        raw = get_client().zrange(QueryStatusManager.IN_PROGRESS_INDEX_KEY, 0, -1)
        return [m.decode("utf-8") if isinstance(m, bytes) else m for m in raw]

    def test_reaps_stale_entry_with_no_heartbeat(self) -> None:
        self._seed_in_progress(pickup_offset_seconds=120)

        reap_orphaned_query_statuses()

        status = self.manager.get_query_status()
        assert status.complete is True
        assert status.error is True
        assert status.error_message is not None
        assert "Query worker terminated unexpectedly" in status.error_message
        assert status.end_time is not None
        assert self._index_members() == []

    def test_does_not_reap_when_heartbeat_present(self) -> None:
        self._seed_in_progress(pickup_offset_seconds=120)
        self.manager.write_worker_heartbeat()

        reap_orphaned_query_statuses()

        status = self.manager.get_query_status()
        assert status.complete is False
        assert status.error is False
        assert self._index_members() == [f"{self.team_id}:{self.query_id}"]

    def test_does_not_reap_recent_entry_within_grace_period(self) -> None:
        self._seed_in_progress(pickup_offset_seconds=10)

        reap_orphaned_query_statuses()

        status = self.manager.get_query_status()
        assert status.complete is False
        assert status.error is False
        assert self._index_members() == [f"{self.team_id}:{self.query_id}"]

    def test_removes_stale_index_entry_when_status_already_complete(self) -> None:
        self._seed_in_progress(pickup_offset_seconds=120, complete=True)

        reap_orphaned_query_statuses()

        # Status is untouched — the reaper only cleans up the dangling index entry.
        status = self.manager.get_query_status()
        assert status.complete is True
        assert status.error is False
        assert self._index_members() == []

    def test_removes_index_entry_when_status_ttl_already_expired(self) -> None:
        pickup_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=120)
        # Add to the index but do NOT store a status — simulates the 20-minute status TTL having expired.
        self.manager.add_to_in_progress_index(pickup_time.timestamp())

        reap_orphaned_query_statuses()

        assert self._index_members() == []

    def test_reaper_lock_prevents_concurrent_runs(self) -> None:
        self._seed_in_progress(pickup_offset_seconds=120)

        # Simulate another reaper holding the lock
        get_client().set("query_async:reaper_lock", "1", nx=True, ex=60)

        reap_orphaned_query_statuses()

        # Status was not updated because this reaper bailed out on the lock
        status = self.manager.get_query_status()
        assert status.complete is False
        assert status.error is False
        assert self._index_members() == [f"{self.team_id}:{self.query_id}"]

    def test_malformed_index_member_is_cleaned_up(self) -> None:
        # Deliberately insert an invalid member with a stale score so the reaper looks at it.
        get_client().zadd(
            QueryStatusManager.IN_PROGRESS_INDEX_KEY,
            {"not-a-valid-format": datetime.datetime.now(datetime.UTC).timestamp() - 300},
        )

        reap_orphaned_query_statuses()

        assert self._index_members() == []

    def test_unregisters_cache_key_mapping_on_reap(self) -> None:
        self._seed_in_progress(pickup_offset_seconds=120)
        cache_key = "test-cache-key"
        # Pre-populate results with a cache_key so the reaper tries to unregister the mapping
        status = self.manager.get_query_status()
        status.results = {"cache_key": cache_key, "results": []}
        self.manager.store_query_status(status)
        self.manager.register_cache_key_mapping(cache_key)

        reap_orphaned_query_statuses()

        assert self.manager.get_running_query_by_cache_key(cache_key) is None

    def test_reaper_increments_prometheus_counter(self) -> None:
        self._seed_in_progress(pickup_offset_seconds=120)

        with patch("posthog.tasks.tasks.QUERY_ASYNC_ORPHANED_REAPED_COUNTER") as mock_counter:
            reap_orphaned_query_statuses()

        mock_counter.inc.assert_called_once()
