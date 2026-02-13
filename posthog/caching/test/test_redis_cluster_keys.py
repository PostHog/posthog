from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized
from redis.crc import key_slot

from posthog.caching.cache_size_tracker import TeamCacheSizeTracker


class TestRedisClusterKeySlots(BaseTest):
    @parameterized.expand(
        [
            ("team_1", 1),
            ("team_42", 42),
            ("team_99999", 99999),
        ]
    )
    def test_hash_tagged_keys_share_same_slot(self, _name: str, team_id: int):
        mock_cache = MagicMock()
        mock_redis = MagicMock()
        mock_redis.register_script = MagicMock(return_value=MagicMock())

        tracker = TeamCacheSizeTracker(team_id, cache_backend=mock_cache, redis_client=mock_redis)

        slots = {
            key_slot(tracker.entries_key.encode()),
            key_slot(tracker.sizes_key.encode()),
            key_slot(tracker.total_key.encode()),
        }
        self.assertEqual(len(slots), 1, f"Keys must hash to same slot, got slots: {slots}")

    @parameterized.expand(
        [
            ("team_1", 1),
            ("team_42", 42),
        ]
    )
    def test_non_cluster_keys_use_old_format(self, _name: str, team_id: int):
        tracker = TeamCacheSizeTracker(team_id)

        self.assertEqual(tracker.entries_key, f"posthog:cache_sizes:{team_id}")
        self.assertEqual(tracker.sizes_key, f"posthog:cache_entry_sizes:{team_id}")
        self.assertEqual(tracker.total_key, f"posthog:cache_total:{team_id}")

    @parameterized.expand(
        [
            ("team_1", 1),
            ("team_42", 42),
        ]
    )
    def test_cluster_keys_use_hash_tag_format(self, _name: str, team_id: int):
        mock_cache = MagicMock()
        mock_redis = MagicMock()
        mock_redis.register_script = MagicMock(return_value=MagicMock())

        tracker = TeamCacheSizeTracker(team_id, cache_backend=mock_cache, redis_client=mock_redis)

        self.assertEqual(tracker.entries_key, f"posthog:cache_sizes:{{{team_id}}}")
        self.assertEqual(tracker.sizes_key, f"posthog:cache_entry_sizes:{{{team_id}}}")
        self.assertEqual(tracker.total_key, f"posthog:cache_total:{{{team_id}}}")
