from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, Mock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone as tz

from posthog.errors import CH_TRANSIENT_ERRORS, CHQueryErrorTooManyBytes
from posthog.models import FeatureFlag
from posthog.tasks.tasks import sync_feature_flag_last_called


def mock_redis_client() -> Mock:
    """Mock Redis client with in-memory storage"""
    mock = Mock()
    mock.storage = {}
    mock.get = lambda k: mock.storage.get(k)
    mock.set = lambda k, v: mock.storage.update({k: v}) or None
    return mock


# Force single-chunk behavior for existing tests so they don't need to handle multiple calls
@override_settings(
    FEATURE_FLAG_LAST_CALLED_AT_SYNC_CHUNK_MINUTES=1440,
    FEATURE_FLAG_LAST_CALLED_AT_SYNC_MAX_LOOKBACK_HOURS=24,
)
class TestSyncFeatureFlagLastCalled(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Clear Redis cache before each test
        cache.clear()

        # Create test flags
        self.flag1 = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag-1",
            created_by=self.user,
            last_called_at=None,
        )
        self.flag2 = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag-2",
            created_by=self.user,
            last_called_at=tz.make_aware(datetime(2024, 1, 1, 0, 0, 0)),
        )
        self.flag3 = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag-3",
            created_by=self.user,
            last_called_at=tz.make_aware(datetime(2024, 6, 1, 0, 0, 0)),
        )

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_no_events_updates_checkpoint(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """When there are no events, checkpoint should still be updated"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock
        mock_sync_execute.return_value = []

        sync_feature_flag_last_called()

        # Verify checkpoint was updated in Redis
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        assert checkpoint_key in redis_mock.storage

        # Verify no flags were updated
        self.flag1.refresh_from_db()
        assert self.flag1.last_called_at is None

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_existing_checkpoint_used(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Task should use existing checkpoint if available"""
        redis_mock = mock_redis_client()
        checkpoint_time = tz.make_aware(datetime(2024, 6, 14, 12, 0, 0))
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        redis_mock.storage[checkpoint_key] = checkpoint_time.isoformat().encode()

        mock_get_client.return_value = redis_mock
        mock_sync_execute.return_value = []

        sync_feature_flag_last_called()

        # Verify first chunk query used checkpoint time
        call_args = mock_sync_execute.call_args_list[0]
        params = call_args[0][1]
        assert params["last_sync_timestamp"] == checkpoint_time

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_updates_null_timestamps(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Flags with null last_called_at should be updated"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock

        latest_timestamp = tz.make_aware(datetime(2024, 6, 15, 11, 0, 0))
        mock_sync_execute.return_value = [
            (self.team.pk, self.flag1.key, latest_timestamp, 100),
        ]

        sync_feature_flag_last_called()

        self.flag1.refresh_from_db()
        assert self.flag1.last_called_at == latest_timestamp

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_updates_only_more_recent_timestamps(
        self, mock_get_client: MagicMock, mock_sync_execute: MagicMock
    ) -> None:
        """Only update timestamps that are more recent than existing ones"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock

        # flag2 has last_called_at=2024-01-01, flag3 has last_called_at=2024-06-01
        older_timestamp = tz.make_aware(datetime(2023, 12, 1, 0, 0, 0))  # Older than flag2's 2024-01-01
        newer_timestamp = tz.make_aware(datetime(2024, 9, 1, 0, 0, 0))  # Newer than flag3's 2024-06-01

        mock_sync_execute.return_value = [
            (self.team.pk, self.flag2.key, older_timestamp, 50),  # Should NOT update (older)
            (self.team.pk, self.flag3.key, newer_timestamp, 75),  # Should update (newer)
        ]

        sync_feature_flag_last_called()

        self.flag2.refresh_from_db()
        self.flag3.refresh_from_db()

        # flag2 should remain unchanged
        assert self.flag2.last_called_at == tz.make_aware(datetime(2024, 1, 1, 0, 0, 0))

        # flag3 should be updated
        assert self.flag3.last_called_at == newer_timestamp

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_handles_nonexistent_flags(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Should gracefully handle flags that don't exist in database"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock

        mock_sync_execute.return_value = [
            (self.team.pk, self.flag1.key, tz.make_aware(datetime(2024, 6, 15, 11, 0, 0)), 100),
            (self.team.pk, "nonexistent-flag", tz.make_aware(datetime(2024, 6, 15, 11, 0, 0)), 50),
        ]

        # Should not raise an exception
        sync_feature_flag_last_called()

        # flag1 should still be updated
        self.flag1.refresh_from_db()
        assert self.flag1.last_called_at is not None

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    @override_settings(FEATURE_FLAG_LAST_CALLED_AT_SYNC_BATCH_SIZE=2)
    def test_bulk_update_respects_batch_size(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Bulk updates should respect configured batch size"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock

        # Create additional flags
        flag4 = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag-4",
            created_by=self.user,
            last_called_at=None,
        )
        flag5 = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag-5",
            created_by=self.user,
            last_called_at=None,
        )

        timestamp = tz.make_aware(datetime(2024, 6, 15, 11, 0, 0))
        mock_sync_execute.return_value = [
            (self.team.pk, self.flag1.key, timestamp, 100),
            (self.team.pk, self.flag2.key, timestamp, 100),
            (self.team.pk, self.flag3.key, timestamp, 100),
            (self.team.pk, flag4.key, timestamp, 100),
            (self.team.pk, flag5.key, timestamp, 100),
        ]

        sync_feature_flag_last_called()

        # Verify all flags were updated
        self.flag1.refresh_from_db()
        self.flag2.refresh_from_db()
        self.flag3.refresh_from_db()
        flag4.refresh_from_db()
        flag5.refresh_from_db()

        assert self.flag1.last_called_at == timestamp
        assert self.flag2.last_called_at == timestamp
        assert self.flag3.last_called_at == timestamp
        assert flag4.last_called_at == timestamp
        assert flag5.last_called_at == timestamp

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_redis_error_falls_back_to_lookback_days(
        self, mock_get_client: MagicMock, mock_sync_execute: MagicMock
    ) -> None:
        """When checkpoint cannot be retrieved, fall back to lookback_days"""
        redis_mock = mock_redis_client()
        # Make redis.get() raise an exception
        redis_mock.get = Mock(side_effect=Exception("Redis error"))
        mock_get_client.return_value = redis_mock
        mock_sync_execute.return_value = []

        sync_feature_flag_last_called()

        # Verify first chunk query used lookback_days
        call_args = mock_sync_execute.call_args_list[0]
        params = call_args[0][1]
        # Should query back 1 day (default FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS)
        last_sync = params["last_sync_timestamp"]
        assert last_sync.year == 2024
        assert last_sync.month == 6
        assert last_sync.day == 14

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.tasks.tasks.get_client")
    def test_concurrent_execution_prevented(self, mock_get_client: MagicMock) -> None:
        """Only one instance should execute at a time due to lock"""
        lock_key = "posthog:feature_flag_last_called_sync:lock"

        # Set lock to prevent execution
        cache.set(lock_key, "locked", timeout=600)

        with patch("posthog.clickhouse.client.sync_execute") as mock_sync_execute:
            sync_feature_flag_last_called()

            # Task should exit early without executing query
            mock_sync_execute.assert_not_called()

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_lock_released_after_execution(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Lock should be released after successful execution"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock
        mock_sync_execute.return_value = []
        lock_key = "posthog:feature_flag_last_called_sync:lock"

        sync_feature_flag_last_called()

        # Lock should be deleted
        assert cache.get(lock_key) is None

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_lock_released_after_exception(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Lock should be released even if task raises exception"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock
        mock_sync_execute.side_effect = Exception("Database error")
        lock_key = "posthog:feature_flag_last_called_sync:lock"

        # Task should raise exception but still clean up lock
        with self.assertRaises(Exception):
            sync_feature_flag_last_called()

        # Lock should be deleted
        assert cache.get(lock_key) is None

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_handles_invalid_timestamps(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Should handle None or invalid timestamps from ClickHouse"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock

        mock_sync_execute.return_value = [
            (self.team.pk, self.flag1.key, None, 10),  # Invalid timestamp
            (self.team.pk, self.flag2.key, tz.make_aware(datetime(2024, 6, 15, 11, 0, 0)), 20),  # Valid timestamp
        ]

        sync_feature_flag_last_called()

        # flag1 should remain unchanged
        self.flag1.refresh_from_db()
        assert self.flag1.last_called_at is None

        # flag2 should be updated
        self.flag2.refresh_from_db()
        assert self.flag2.last_called_at is not None

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_checkpoint_updated_to_current_sync_timestamp(
        self, mock_get_client: MagicMock, mock_sync_execute: MagicMock
    ) -> None:
        """
        Checkpoint should be updated to the wall-clock time of the sync run, not max event timestamp
        """
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock

        mock_sync_execute.return_value = [
            (self.team.pk, self.flag1.key, tz.make_aware(datetime(2024, 6, 15, 10, 0, 0)), 10),
            (self.team.pk, self.flag2.key, tz.make_aware(datetime(2024, 6, 15, 11, 30, 0)), 20),
            (self.team.pk, self.flag3.key, tz.make_aware(datetime(2024, 6, 15, 11, 59, 59)), 30),
        ]

        sync_feature_flag_last_called()

        # Checkpoint should be set to current_sync_timestamp (frozen at 2024-06-15T12:00:00Z)
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        stored_timestamp = redis_mock.storage.get(checkpoint_key)
        assert stored_timestamp is not None
        assert "2024-06-15" in stored_timestamp
        assert "2024-06-15T12:00:00" in stored_timestamp

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    @override_settings(FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT=2)
    def test_respects_clickhouse_limit(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Query should respect FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT setting"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock
        mock_sync_execute.return_value = []

        sync_feature_flag_last_called()

        # Verify query includes LIMIT clause with configured value
        call_args = mock_sync_execute.call_args_list[0]
        params = call_args[0][1]
        assert params["limit"] == 2

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_handles_naive_datetimes_from_clickhouse(
        self, mock_get_client: MagicMock, mock_sync_execute: MagicMock
    ) -> None:
        """ClickHouse returns naive datetimes - verify they're converted to timezone-aware"""
        redis_mock = mock_redis_client()
        mock_get_client.return_value = redis_mock

        # ClickHouse returns naive datetimes (no timezone info) - this is what really happens
        naive_timestamp = datetime(2024, 6, 15, 11, 0, 0)  # No tz.make_aware!

        # flag3 has a timezone-aware last_called_at from Django
        assert self.flag3.last_called_at is not None
        assert self.flag3.last_called_at.tzinfo is not None

        mock_sync_execute.return_value = [
            (self.team.pk, self.flag3.key, naive_timestamp, 100),
        ]

        # Should succeed - naive datetimes are converted to timezone-aware before comparison
        sync_feature_flag_last_called()

        # Flag should be updated with the timezone-aware version of the naive timestamp
        self.flag3.refresh_from_db()
        assert self.flag3.last_called_at is not None
        assert self.flag3.last_called_at.tzinfo is not None  # Must be timezone-aware
        # The stored timestamp should match the naive timestamp when interpreted in default timezone
        assert self.flag3.last_called_at == tz.make_aware(naive_timestamp)


@override_settings(
    FEATURE_FLAG_LAST_CALLED_AT_SYNC_CHUNK_MINUTES=5,
    FEATURE_FLAG_LAST_CALLED_AT_SYNC_MAX_LOOKBACK_HOURS=6,
)
class TestSyncFeatureFlagLastCalledChunking(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

        self.flag1 = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag-1",
            created_by=self.user,
            last_called_at=None,
        )

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_chunking_splits_large_window(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """A 20-minute window with 5-minute chunks should produce 4 ClickHouse queries"""
        redis_mock = mock_redis_client()
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        checkpoint_time = tz.make_aware(datetime(2024, 6, 15, 11, 40, 0))  # 20 min ago
        redis_mock.storage[checkpoint_key] = checkpoint_time.isoformat().encode()
        mock_get_client.return_value = redis_mock
        mock_sync_execute.return_value = []

        sync_feature_flag_last_called()

        assert mock_sync_execute.call_count == 4

        # Verify chunk boundaries are correct
        expected_starts = [
            tz.make_aware(datetime(2024, 6, 15, 11, 40, 0)),
            tz.make_aware(datetime(2024, 6, 15, 11, 45, 0)),
            tz.make_aware(datetime(2024, 6, 15, 11, 50, 0)),
            tz.make_aware(datetime(2024, 6, 15, 11, 55, 0)),
        ]
        for i, call in enumerate(mock_sync_execute.call_args_list):
            params = call[0][1]
            assert params["last_sync_timestamp"] == expected_starts[i], f"Chunk {i} start mismatch"

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_checkpoint_not_updated_on_failure(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """On scan failure, checkpoint should remain unchanged so the window is retried"""
        redis_mock = mock_redis_client()
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        # 15 min ago = 3 chunks
        checkpoint_time = tz.make_aware(datetime(2024, 6, 15, 11, 45, 0))
        redis_mock.storage[checkpoint_key] = checkpoint_time.isoformat().encode()
        mock_get_client.return_value = redis_mock

        # First chunk succeeds, second chunk fails
        mock_sync_execute.side_effect = [[], Exception("ClickHouse error")]

        with self.assertRaises(Exception):
            sync_feature_flag_last_called()

        # Checkpoint should remain at the original value (no per-chunk advancement)
        stored = redis_mock.storage.get(checkpoint_key)
        assert stored == checkpoint_time.isoformat().encode()

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_max_lookback_caps_stale_checkpoint(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """A checkpoint older than max_lookback_hours should be capped"""
        redis_mock = mock_redis_client()
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        # 3 days ago — well beyond the 6-hour max lookback
        stale_checkpoint = tz.make_aware(datetime(2024, 6, 12, 12, 0, 0))
        redis_mock.storage[checkpoint_key] = stale_checkpoint.isoformat().encode()
        mock_get_client.return_value = redis_mock
        mock_sync_execute.return_value = []

        sync_feature_flag_last_called()

        # First chunk should start at max_lookback (6 hours ago = 06:00:00), not 3 days ago
        first_call_params = mock_sync_execute.call_args_list[0][0][1]
        first_start = first_call_params["last_sync_timestamp"]
        expected_cap = tz.make_aware(datetime(2024, 6, 15, 6, 0, 0))
        assert first_start == expected_cap

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_merges_results_across_chunks(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """Same flag appearing in multiple chunks should use the max timestamp"""
        redis_mock = mock_redis_client()
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        checkpoint_time = tz.make_aware(datetime(2024, 6, 15, 11, 50, 0))  # 10 min ago = 2 chunks
        redis_mock.storage[checkpoint_key] = checkpoint_time.isoformat().encode()
        mock_get_client.return_value = redis_mock

        earlier_ts = tz.make_aware(datetime(2024, 6, 15, 11, 52, 0))
        later_ts = tz.make_aware(datetime(2024, 6, 15, 11, 58, 0))

        # Chunk 1 returns earlier timestamp, chunk 2 returns later timestamp for same flag
        mock_sync_execute.side_effect = [
            [(self.team.pk, self.flag1.key, earlier_ts, 50)],
            [(self.team.pk, self.flag1.key, later_ts, 30)],
        ]

        sync_feature_flag_last_called()

        # Both chunks should have been queried
        assert mock_sync_execute.call_count == 2

        # Flag should have the later (max) timestamp
        self.flag1.refresh_from_db()
        assert self.flag1.last_called_at == later_ts

    @freeze_time("2024-06-15 12:00:00")
    @patch("posthog.clickhouse.client.sync_execute")
    @patch("posthog.tasks.tasks.get_client")
    def test_all_none_timestamps_skips_pg_query(self, mock_get_client: MagicMock, mock_sync_execute: MagicMock) -> None:
        """When all CH timestamps are None, flag_updates is empty and PG should not be queried"""
        redis_mock = mock_redis_client()
        checkpoint_key = "posthog:feature_flag_last_called_sync:last_timestamp"
        checkpoint_time = tz.make_aware(datetime(2024, 6, 15, 11, 50, 0))
        redis_mock.storage[checkpoint_key] = checkpoint_time.isoformat().encode()
        mock_get_client.return_value = redis_mock

        # Return rows with None timestamps across two chunks
        mock_sync_execute.side_effect = [
            [(self.team.pk, self.flag1.key, None, 10)],
            [(self.team.pk, self.flag1.key, None, 5)],
        ]

        with patch.object(FeatureFlag.objects, "filter") as mock_filter:
            sync_feature_flag_last_called()
            mock_filter.assert_not_called()

        # Checkpoint should still be updated
        stored = redis_mock.storage.get(checkpoint_key)
        assert stored is not None
        assert "2024-06-15T12:00:00" in stored

        # Flag should remain unchanged
        self.flag1.refresh_from_db()
        assert self.flag1.last_called_at is None

    def test_no_retry_on_too_many_bytes(self) -> None:
        """CHQueryErrorTooManyBytes should not be in the autoretry_for tuple"""
        autoretry_for = sync_feature_flag_last_called.autoretry_for
        assert CHQueryErrorTooManyBytes not in autoretry_for
        # Transient errors should still be retried
        for error_cls in CH_TRANSIENT_ERRORS:
            assert error_cls in autoretry_for
