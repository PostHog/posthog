from posthog.test.base import BaseTest

from django.core.cache import cache
from django.test import override_settings

from posthog.caching.cache_size_tracker import TeamCacheSizeTracker, get_team_cache_limit
from posthog.models import Team


class TestTeamCacheSizeTracker(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.tracker = TeamCacheSizeTracker(self.team.pk)
        self.tracker.purge()

    def tearDown(self) -> None:
        self.tracker.purge()
        cache.delete("test_key_1")
        cache.delete("test_key_2")
        cache.delete("test_key_3")
        cache.delete("expired_key")
        cache.delete("real_key")
        super().tearDown()

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
        # Add entries with small delays to ensure different timestamps
        self.tracker.track_cache_write("test_key_1", 100)
        cache.set("test_key_1", "data1")

        self.tracker.track_cache_write("test_key_2", 200)
        cache.set("test_key_2", "data2")

        self.tracker.track_cache_write("test_key_3", 300)
        cache.set("test_key_3", "data3")

        self.assertEqual(self.tracker.get_total_size(), 600)

        # Evict to make room for 200 bytes with limit of 500
        # Should evict test_key_1 (oldest, 100 bytes) and test_key_2 (next oldest, 200 bytes)
        evicted = self.tracker.evict_until_under_limit(500, 200)

        # Should have evicted oldest entries
        self.assertIn("test_key_1", evicted)
        self.assertIn("test_key_2", evicted)
        # Total should now be under limit + new entry size
        self.assertLessEqual(self.tracker.get_total_size() + 200, 500)
        # Newest entry should still exist
        self.assertIsNotNone(cache.get("test_key_3"))

    def test_evict_cleans_up_expired_keys(self):
        # Track a key but don't actually set it in cache (simulates TTL expiration)
        self.tracker.track_cache_write("expired_key", 1000)
        # Don't set cache.set() - simulating expired key

        # Track a real key
        self.tracker.track_cache_write("real_key", 500)
        cache.set("real_key", "data")

        # Total includes the "expired" key
        self.assertEqual(self.tracker.get_total_size(), 1500)

        # Evict should clean up expired key first
        evicted = self.tracker.evict_until_under_limit(1000, 100)

        # Expired key should be cleaned up (not in evicted list since it wasn't actually evicted)
        self.assertNotIn("expired_key", evicted)
        # Real key should still exist
        self.assertIsNotNone(cache.get("real_key"))
        # Total should now be correct (only real_key)
        self.assertEqual(self.tracker.get_total_size(), 500)

    def test_evict_returns_empty_when_under_limit(self):
        self.tracker.track_cache_write("test_key_1", 100)
        cache.set("test_key_1", "data1")

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
        self.tracker.set("test_key_1", data, len(data), 300)

        # Cache should be set
        self.assertEqual(cache.get("test_key_1"), data)
        # Tracking should be updated
        self.assertEqual(self.tracker.get_total_size(), len(data))

    @override_settings(TEAM_CACHE_SIZE_LIMIT_BYTES=500)
    def test_set_method_triggers_eviction_when_over_limit(self):
        # First write - under limit
        data1 = b"x" * 200
        cache.set("test_key_1", data1)
        self.tracker.track_cache_write("test_key_1", len(data1))

        data2 = b"y" * 200
        cache.set("test_key_2", data2)
        self.tracker.track_cache_write("test_key_2", len(data2))

        # This should trigger eviction of test_key_1
        data3 = b"z" * 200
        evicted = self.tracker.set("test_key_3", data3, len(data3), 300)

        self.assertIn("test_key_1", evicted)
        self.assertIsNone(cache.get("test_key_1"))
        self.assertIsNotNone(cache.get("test_key_3"))

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
        # Track keys but don't set them in cache (simulates TTL expiration)
        self.tracker.track_cache_write("stale_key_1", 1000)
        self.tracker.track_cache_write("stale_key_2", 1000)
        # Also add a real key
        self.tracker.track_cache_write("real_key", 500)
        cache.set("real_key", "data")

        # Total is inflated due to stale entries
        self.assertEqual(self.tracker.get_total_size(), 2500)

        # Evict to make room - stale entries are cleaned up first (not counted as evicted)
        evicted = self.tracker.evict_until_under_limit(1000, 100)

        # Stale entries cleaned up, real_key not evicted (500 + 100 <= 1000)
        self.assertEqual(evicted, [])
        self.assertEqual(self.tracker.get_total_size(), 500)
        self.assertIsNotNone(cache.get("real_key"))

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
        cache.set("test_key_1", b"x" * 100)
        self.tracker.track_cache_write("test_key_1", 100)
        cache.set("test_key_2", b"y" * 100)
        self.tracker.track_cache_write("test_key_2", 100)

        self.assertEqual(self.tracker.get_total_size(), 200)

        large_data = b"z" * 600
        evicted = self.tracker.set("large_key", large_data, len(large_data), 300)

        self.assertIn("test_key_1", evicted)
        self.assertIn("test_key_2", evicted)
        self.assertEqual(cache.get("large_key"), large_data)
        self.assertEqual(self.tracker.get_total_size(), 600)


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
    def test_get_team_cache_limit_casts_string_to_int(self):
        # Test that string values are cast to int
        self.team.extra_settings = {"cache_size_limit_bytes": "1000000000"}
        self.team.save()

        limit = get_team_cache_limit(self.team.pk)
        self.assertEqual(limit, 1_000_000_000)
