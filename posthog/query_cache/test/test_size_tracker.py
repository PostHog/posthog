from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError
from django.test import override_settings

import fakeredis
from parameterized import parameterized

from posthog.models import Team
from posthog.query_cache.size_tracker import TeamCacheSizeTracker, get_team_cache_limit
from posthog.query_cache.storage import BLOB_DELETE_DELAY_SECONDS, S3BlobPointer, encode_pointer, entry_redis_key

ENTRY_KEYS = [
    "test_key",
    "test_key_1",
    "test_key_2",
    "test_key_3",
    "expired_key",
    "real_key",
    "large_key",
]


class TestTeamCacheSizeTracker(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.tracker = TeamCacheSizeTracker(self.team.pk)
        self.tracker.purge()

    def tearDown(self) -> None:
        self.tracker.purge()
        self.tracker.redis_client.delete(*(entry_redis_key(key) for key in ENTRY_KEYS))
        super().tearDown()

    def _seed_entry(self, cache_key: str, data: bytes) -> None:
        self.tracker.redis_client.set(entry_redis_key(cache_key), data)

    def _entry(self, cache_key: str) -> bytes | None:
        return self.tracker.redis_client.get(entry_redis_key(cache_key))

    def test_track_cache_write_increments_total(self):
        self.assertEqual(self.tracker.get_total_size(), 0)

        self.tracker.track_cache_write("test_key_1", 1000)
        self.assertEqual(self.tracker.get_total_size(), 1000)

        self.tracker.track_cache_write("test_key_2", 500)
        self.assertEqual(self.tracker.get_total_size(), 1500)

    def test_track_cache_write_handles_overwrite(self):
        self.tracker.track_cache_write("test_key_1", 1000)
        self.assertEqual(self.tracker.get_total_size(), 1000)

        # Overwrite with larger value
        self.tracker.track_cache_write("test_key_1", 2000)
        self.assertEqual(self.tracker.get_total_size(), 2000)

        # Overwrite with smaller value
        self.tracker.track_cache_write("test_key_1", 500)
        self.assertEqual(self.tracker.get_total_size(), 500)

    def test_get_total_size_returns_correct_value(self):
        self.assertEqual(self.tracker.get_total_size(), 0)

        self.tracker.track_cache_write("test_key_1", 100)
        self.tracker.track_cache_write("test_key_2", 200)
        self.tracker.track_cache_write("test_key_3", 300)

        self.assertEqual(self.tracker.get_total_size(), 600)

    def test_evict_until_under_limit_removes_oldest(self):
        self.tracker.track_cache_write("test_key_1", 100)
        self.tracker.track_cache_write("test_key_2", 200)
        self.tracker.track_cache_write("test_key_3", 300)
        self._seed_entry("test_key_1", b"data1")
        self._seed_entry("test_key_2", b"data2")
        self._seed_entry("test_key_3", b"data3")

        self.assertEqual(self.tracker.get_total_size(), 600)

        # Evict to make room for 200 bytes with limit of 500
        # Should evict test_key_1 (oldest, 100 bytes) and test_key_2 (next oldest, 200 bytes)
        evicted = self.tracker.evict_until_under_limit(500, 200)

        # Should have evicted oldest entries
        self.assertIn("test_key_1", evicted)
        self.assertIn("test_key_2", evicted)
        self.assertIsNone(self.tracker._get_key_size("test_key_1"))
        self.assertIsNone(self.tracker._get_key_size("test_key_2"))
        self.assertIsNone(self.tracker.redis_client.zscore(self.tracker.entries_key, "test_key_1"))
        self.assertIsNone(self.tracker.redis_client.zscore(self.tracker.entries_key, "test_key_2"))
        # Total should now be under limit + new entry size
        self.assertLessEqual(self.tracker.get_total_size() + 200, 500)
        # Newest entry should still exist
        self.assertIsNotNone(self._entry("test_key_3"))

    def test_evict_cleans_up_expired_keys(self):
        # Track a key but don't actually store an entry for it (simulates TTL expiration)
        self.tracker.track_cache_write("expired_key", 1000)

        # Track a real key
        self.tracker.track_cache_write("real_key", 500)
        self._seed_entry("real_key", b"data")

        # Total includes the "expired" key
        self.assertEqual(self.tracker.get_total_size(), 1500)

        # Evict should clean up expired key first
        evicted = self.tracker.evict_until_under_limit(1000, 100)

        # Expired key should be cleaned up (not in evicted list since it wasn't actually evicted)
        self.assertNotIn("expired_key", evicted)
        # Real key should still exist
        self.assertIsNotNone(self._entry("real_key"))
        # Total should now be correct (only real_key)
        self.assertEqual(self.tracker.get_total_size(), 500)

    def test_evict_returns_empty_when_under_limit(self):
        self.tracker.track_cache_write("test_key_1", 100)
        self._seed_entry("test_key_1", b"data1")

        # Already under limit
        evicted = self.tracker.evict_until_under_limit(1000, 100)
        self.assertEqual(evicted, [])
        self.assertEqual(self.tracker.get_total_size(), 100)

    def test_purge_removes_all_tracking_data(self):
        self.tracker.track_cache_write("test_key_1", 1000)
        self.tracker.track_cache_write("test_key_2", 2000)
        self.assertEqual(self.tracker.get_total_size(), 3000)

        self.tracker.purge()

        self.assertEqual(self.tracker.get_total_size(), 0)
        self.assertIsNone(self.tracker._get_key_size("test_key_1"))
        self.assertIsNone(self.tracker._get_key_size("test_key_2"))

    def test_set_method_writes_cache_and_tracks(self):
        data = b"test_data_content"
        self.tracker.set("test_key_1", data, 300)

        # Cache should be set
        self.assertEqual(self._entry("test_key_1"), data)
        # Tracking should be updated
        self.assertEqual(self.tracker.get_total_size(), len(data))

    @parameterized.expand(
        [
            ("pointer", encode_pointer(S3BlobPointer(bucket="cache-bucket", key="query_cache/1/old")), True),
            ("inline_blob", b"plain-old-bytes", False),
            ("absent", None, False),
        ]
    )
    def test_set_schedules_delayed_delete_only_for_replaced_pointers(self, _name, old_value, expect_delete):
        if old_value is not None:
            self._seed_entry("test_key_1", old_value)

        with patch("posthog.query_cache.tasks.delete_query_cache_blob.apply_async") as apply_async:
            self.tracker.set("test_key_1", b"new-data", 300)

        self.assertEqual(self._entry("test_key_1"), b"new-data")
        if not expect_delete:
            apply_async.assert_not_called()
            return
        apply_async.assert_called_once()
        self.assertEqual(apply_async.call_args.kwargs["countdown"], BLOB_DELETE_DELAY_SECONDS)
        task_kwargs = apply_async.call_args.kwargs["kwargs"]
        self.assertEqual(task_kwargs["bucket"], "cache-bucket")
        self.assertEqual(task_kwargs["key"], "query_cache/1/old")
        self.assertEqual(task_kwargs["trigger"], "replaced")

    def test_eviction_schedules_delete_for_evicted_pointer_entries(self):
        pointer = encode_pointer(S3BlobPointer(bucket="cache-bucket", key="query_cache/1/evicted"))
        self._seed_entry("test_key_1", pointer)
        self.tracker.track_cache_write("test_key_1", 200)
        self._seed_entry("test_key_2", b"y" * 200)
        self.tracker.track_cache_write("test_key_2", 200)

        with patch("posthog.query_cache.tasks.delete_query_cache_blob.apply_async") as apply_async:
            evicted = self.tracker.evict_until_under_limit(300, 250)

        # Both entries go, but only the pointer-backed one has a blob to delete
        self.assertEqual(evicted, ["test_key_1", "test_key_2"])
        apply_async.assert_called_once()
        task_kwargs = apply_async.call_args.kwargs["kwargs"]
        self.assertEqual(task_kwargs["key"], "query_cache/1/evicted")
        self.assertEqual(task_kwargs["trigger"], "evicted")

    def test_broker_failure_does_not_break_the_cache_write(self):
        self._seed_entry("test_key_1", encode_pointer(S3BlobPointer(bucket="cache-bucket", key="query_cache/1/old")))

        with patch(
            "posthog.query_cache.tasks.delete_query_cache_blob.apply_async", side_effect=Exception("broker down")
        ):
            self.tracker.set("test_key_1", b"new-data", 300)

        self.assertEqual(self._entry("test_key_1"), b"new-data")
        self.assertEqual(self.tracker.get_total_size(), len(b"new-data"))

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500)
    def test_set_method_triggers_eviction_when_over_limit(self):
        # First write - under limit
        data1 = b"x" * 200
        self._seed_entry("test_key_1", data1)
        self.tracker.track_cache_write("test_key_1", len(data1))

        data2 = b"y" * 200
        self._seed_entry("test_key_2", data2)
        self.tracker.track_cache_write("test_key_2", len(data2))

        # This should trigger eviction of test_key_1
        data3 = b"z" * 200
        evicted = self.tracker.set("test_key_3", data3, 300)

        self.assertIn("test_key_1", evicted)
        self.assertIsNone(self._entry("test_key_1"))
        self.assertIsNone(self.tracker._get_key_size("test_key_1"))
        self.assertIsNone(self.tracker.redis_client.zscore(self.tracker.entries_key, "test_key_1"))
        self.assertIsNotNone(self._entry("test_key_3"))

    def test_remove_tracking_is_idempotent(self):
        self.tracker.track_cache_write("test_key", 1000)
        self.assertEqual(self.tracker.get_total_size(), 1000)

        # Pop it from sorted set (simulating zpopmin in eviction)
        self.tracker.redis_client.zpopmin(self.tracker.entries_key, 1)

        # Remove tracking twice - second call should be no-op
        removed1 = self.tracker._remove_tracking("test_key")
        removed2 = self.tracker._remove_tracking("test_key")

        self.assertEqual(removed1, 1000)
        self.assertEqual(removed2, 0)
        self.assertEqual(self.tracker.get_total_size(), 0)

    def test_stale_tracking_cleaned_during_eviction(self):
        # Track keys but don't store entries for them (simulates TTL expiration)
        self.tracker.track_cache_write("stale_key_1", 1000)
        self.tracker.track_cache_write("stale_key_2", 1000)
        # Also add a real key
        self.tracker.track_cache_write("real_key", 500)
        self._seed_entry("real_key", b"data")

        # Total is inflated due to stale entries
        self.assertEqual(self.tracker.get_total_size(), 2500)

        # Evict to make room - stale entries are cleaned up first (not counted as evicted)
        evicted = self.tracker.evict_until_under_limit(1000, 100)

        # Stale entries cleaned up, real_key not evicted (500 + 100 <= 1000)
        self.assertEqual(evicted, [])
        self.assertEqual(self.tracker.get_total_size(), 500)
        self.assertIsNotNone(self._entry("real_key"))

    def test_team_isolation(self):
        tracker_team_a = TeamCacheSizeTracker(self.team.pk)
        tracker_team_a.purge()

        team_b = Team.objects.create(organization=self.organization, name="Team B")
        tracker_team_b = TeamCacheSizeTracker(team_b.pk)
        tracker_team_b.purge()

        tracker_team_a.track_cache_write("key_a", 1000)
        tracker_team_b.track_cache_write("key_b", 2000)

        self.assertEqual(tracker_team_a.get_total_size(), 1000)
        self.assertEqual(tracker_team_b.get_total_size(), 2000)

        tracker_team_a.purge()
        tracker_team_b.purge()

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500)
    def test_entry_larger_than_limit_evicts_all(self):
        self._seed_entry("test_key_1", b"x" * 100)
        self.tracker.track_cache_write("test_key_1", 100)
        self._seed_entry("test_key_2", b"y" * 100)
        self.tracker.track_cache_write("test_key_2", 100)

        self.assertEqual(self.tracker.get_total_size(), 200)

        large_data = b"z" * 600
        evicted = self.tracker.set("large_key", large_data, 300)

        self.assertIn("test_key_1", evicted)
        self.assertIn("test_key_2", evicted)
        self.assertEqual(self._entry("large_key"), large_data)
        self.assertIsNone(self.tracker._get_key_size("test_key_1"))
        self.assertIsNone(self.tracker._get_key_size("test_key_2"))
        self.assertIsNone(self.tracker.redis_client.zscore(self.tracker.entries_key, "test_key_1"))
        self.assertIsNone(self.tracker.redis_client.zscore(self.tracker.entries_key, "test_key_2"))
        self.assertEqual(self.tracker.get_total_size(), 600)

    def test_set_and_read_through_injected_redis_client(self):
        injected = fakeredis.FakeRedis()
        tracker = TeamCacheSizeTracker(self.team.pk, redis_client=injected)
        tracker.purge()

        data = b"test_data_content"
        tracker.set("test_key", data, 300)

        # Entry and tracking both live in the injected client, not the shared one
        self.assertEqual(injected.get(entry_redis_key("test_key")), data)
        self.assertIsNone(self._entry("test_key"))
        self.assertEqual(tracker.get_total_size(), len(data))

        tracker.purge()


class TestGetTeamCacheLimit(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Clear the cache_for cache to ensure fresh lookups
        get_team_cache_limit._cache.clear()

    def tearDown(self) -> None:
        get_team_cache_limit._cache.clear()
        super().tearDown()

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500_000_000)
    def test_get_team_cache_limit_uses_default(self):
        limit = get_team_cache_limit(self.team.pk)
        self.assertEqual(limit, 500_000_000)

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500_000_000)
    def test_get_team_cache_limit_uses_override(self):
        # Set per-team override
        self.team.extra_settings = {"cache_size_limit_bytes": 2_000_000_000}
        self.team.save()

        limit = get_team_cache_limit(self.team.pk)
        self.assertEqual(limit, 2_000_000_000)

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500_000_000)
    def test_get_team_cache_limit_returns_default_for_nonexistent_team(self):
        limit = get_team_cache_limit(999999)
        self.assertEqual(limit, 500_000_000)

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500_000_000)
    def test_get_team_cache_limit_ignores_empty_extra_settings(self):
        self.team.extra_settings = {}
        self.team.save()

        limit = get_team_cache_limit(self.team.pk)
        self.assertEqual(limit, 500_000_000)

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500_000_000)
    def test_get_team_cache_limit_falls_back_to_default_when_postgres_errors(self):
        with patch.object(Team.objects, "only", side_effect=OperationalError("query_wait_timeout")):
            limit = get_team_cache_limit(self.team.pk)

        self.assertEqual(limit, 500_000_000)

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500_000_000)
    def test_get_team_cache_limit_casts_string_to_int(self):
        # Test that string values are cast to int
        self.team.extra_settings = {"cache_size_limit_bytes": "1000000000"}
        self.team.save()

        limit = get_team_cache_limit(self.team.pk)
        self.assertEqual(limit, 1_000_000_000)
