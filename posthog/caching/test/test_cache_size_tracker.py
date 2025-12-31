import time

from posthog.test.base import BaseTest

from django.core.cache import cache
from django.test import override_settings

from posthog.caching.cache_size_tracker import TeamCacheSizeTracker, get_team_cache_limit


class TestTeamCacheSizeTracker(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.tracker = TeamCacheSizeTracker(self.team.pk)
        # Clean up any existing tracking data
        self.tracker.redis_client.delete(self.tracker.entries_key)
        self.tracker.redis_client.delete(self.tracker.sizes_key)
        self.tracker.redis_client.delete(self.tracker.total_key)

    def tearDown(self) -> None:
        # Clean up tracking data
        self.tracker.redis_client.delete(self.tracker.entries_key)
        self.tracker.redis_client.delete(self.tracker.sizes_key)
        self.tracker.redis_client.delete(self.tracker.total_key)
        # Clean up any cache keys we created
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
        time.sleep(0.01)

        self.tracker.track_cache_write("test_key_2", 200)
        cache.set("test_key_2", "data2")
        time.sleep(0.01)

        self.tracker.track_cache_write("test_key_3", 300)
        cache.set("test_key_3", "data3")

        self.assertEqual(self.tracker.get_total_size(), 600)

        # Evict to make room for 200 bytes with limit of 500
        # Should evict test_key_1 (oldest, 100 bytes) and test_key_2 (next oldest, 200 bytes)
        evicted = self.tracker.evict_until_under_limit(500, 200)

        # Should have evicted oldest entries
        self.assertIn("test_key_1", evicted)
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


class TestGetTeamCacheLimit(BaseTest):
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
