import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from unittest.mock import Mock, patch

from django.conf import settings
from django.utils import timezone as django_timezone

from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.temporal.feature_flag_sync.workflow import (
    FEATURE_FLAG_LAST_CALLED_SYNC_KEY,
    FlagSyncResult,
    SyncFeatureFlagLastCalledInputs,
    SyncFeatureFlagLastCalledWorkflow,
    sync_feature_flag_last_called_activity,
)


class TestSyncFeatureFlagLastCalledActivity:
    @pytest.mark.django_db
    def test_activity_with_no_events(self, activity_environment, team):
        """Test activity behavior when no events are found."""
        inputs = SyncFeatureFlagLastCalledInputs()

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis
                mock_sync_execute.return_value = []

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                assert result.updated_count == 0
                assert result.processed_events == 0
                assert result.sync_duration_seconds > 0

                # Verify Redis checkpoint was updated
                mock_redis.set.assert_called_once()
                call_args = mock_redis.set.call_args[0]
                assert call_args[0] == FEATURE_FLAG_LAST_CALLED_SYNC_KEY

    @pytest.mark.django_db
    def test_activity_with_existing_checkpoint(self, activity_environment, team):
        """Test activity with existing Redis checkpoint."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create a feature flag
        flag = FeatureFlag.objects.create(team=team, key="test-flag", name="Test Flag")

        last_sync = django_timezone.now() - timedelta(hours=1)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = last_sync.isoformat().encode()
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse result
                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, "test-flag", new_timestamp, 5)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                assert result.updated_count == 1
                assert result.processed_events == 5

                # Verify flag was updated
                flag.refresh_from_db()
                assert flag.last_called_at is not None
                assert flag.last_called_at.replace(microsecond=0) == new_timestamp.replace(microsecond=0)

    @pytest.mark.django_db
    def test_activity_only_updates_more_recent_timestamps(self, activity_environment, team):
        """Test that activity only updates flags with more recent timestamps."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create a feature flag with existing timestamp
        old_timestamp = django_timezone.now() - timedelta(hours=2)
        flag = FeatureFlag.objects.create(team=team, key="test-flag", name="Test Flag", last_called_at=old_timestamp)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse result with older timestamp
                older_timestamp = django_timezone.now() - timedelta(hours=3)
                mock_sync_execute.return_value = [(team.id, "test-flag", older_timestamp, 3)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should not update since timestamp is older
                assert result.updated_count == 0
                assert result.processed_events == 3

                # Verify flag timestamp unchanged
                flag.refresh_from_db()
                assert flag.last_called_at.replace(microsecond=0) == old_timestamp.replace(microsecond=0)

    @pytest.mark.django_db
    def test_activity_updates_null_timestamps(self, activity_environment, team):
        """Test that activity updates flags with null last_called_at."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create a feature flag without timestamp
        flag = FeatureFlag.objects.create(team=team, key="test-flag", name="Test Flag", last_called_at=None)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, "test-flag", new_timestamp, 1)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                assert result.updated_count == 1
                assert result.processed_events == 1

                # Verify flag was updated
                flag.refresh_from_db()
                assert flag.last_called_at is not None

    @pytest.mark.django_db
    def test_activity_handles_non_existent_flags(self, activity_environment, team):
        """Test that activity handles ClickHouse events for non-existent flags."""
        inputs = SyncFeatureFlagLastCalledInputs()

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock result for non-existent flag
                mock_sync_execute.return_value = [(team.id, "non-existent-flag", django_timezone.now(), 2)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should not update any flags
                assert result.updated_count == 0
                assert result.processed_events == 2

    @pytest.mark.django_db
    def test_activity_bulk_update_performance(self, activity_environment, team):
        """Test bulk update performance with multiple flags."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create multiple flags
        flags = []
        for i in range(5):
            flag = FeatureFlag.objects.create(team=team, key=f"test-flag-{i}", name=f"Test Flag {i}")
            flags.append(flag)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock multiple results
                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, f"test-flag-{i}", new_timestamp, i + 1) for i in range(5)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                assert result.updated_count == 5
                assert result.processed_events == 15  # 1+2+3+4+5

                # Verify all flags were updated
                for flag in flags:
                    flag.refresh_from_db()
                    assert flag.last_called_at is not None

    @pytest.mark.django_db
    def test_activity_redis_error_handling(self, activity_environment, team):
        """Test handling of Redis errors."""
        inputs = SyncFeatureFlagLastCalledInputs()

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                # Simulate Redis error by raising exception on get
                mock_redis.get.side_effect = Exception("Redis connection error")
                mock_get_client.return_value = mock_redis

                mock_sync_execute.return_value = []

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should complete successfully with fallback behavior
                assert result.updated_count == 0
                assert result.processed_events == 0

    @pytest.mark.django_db
    def test_activity_invalid_timestamp_handling(self, activity_environment, team):
        """Test handling of invalid timestamps from Redis."""
        inputs = SyncFeatureFlagLastCalledInputs()

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                # Return invalid timestamp format
                mock_redis.get.return_value = b"invalid-timestamp"
                mock_get_client.return_value = mock_redis

                mock_sync_execute.return_value = []

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should complete successfully with fallback to 1 day ago
                assert result.updated_count == 0
                assert result.processed_events == 0


class TestSyncFeatureFlagLastCalledWorkflow:
    def test_parse_inputs_empty(self):
        """Test parsing empty inputs."""
        result = SyncFeatureFlagLastCalledWorkflow.parse_inputs([])
        assert isinstance(result, SyncFeatureFlagLastCalledInputs)

    def test_parse_inputs_with_data(self):
        """Test parsing inputs with JSON data."""
        inputs_json = json.dumps({})
        result = SyncFeatureFlagLastCalledWorkflow.parse_inputs([inputs_json])
        assert isinstance(result, SyncFeatureFlagLastCalledInputs)

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_workflow_execution(self, team):
        """Test full workflow execution."""
        # Create a test flag
        await sync_to_async(FeatureFlag.objects.create)(team=team, key="test-flag", name="Test Flag")

        inputs = SyncFeatureFlagLastCalledInputs()

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[SyncFeatureFlagLastCalledWorkflow],
                activities=[sync_feature_flag_last_called_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                debug_mode=True,
            ):
                with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
                    with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                        mock_redis = Mock()
                        mock_redis.get.return_value = None
                        mock_get_client.return_value = mock_redis

                        # Mock ClickHouse result
                        new_timestamp = django_timezone.now()
                        mock_sync_execute.return_value = [(team.id, "test-flag", new_timestamp, 3)]

                        result = await activity_environment.client.execute_workflow(
                            SyncFeatureFlagLastCalledWorkflow.run,
                            inputs,
                            id=str(uuid.uuid4()),
                            task_queue=settings.TEMPORAL_TASK_QUEUE,
                        )

                        assert isinstance(result, FlagSyncResult)
                        assert result.updated_count == 1
                        assert result.processed_events == 3
                        assert result.sync_duration_seconds > 0

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_workflow_retry_behavior(self, team):
        """Test workflow retry behavior on activity failure."""
        inputs = SyncFeatureFlagLastCalledInputs()

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[SyncFeatureFlagLastCalledWorkflow],
                activities=[sync_feature_flag_last_called_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                debug_mode=True,
            ):
                with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
                    with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                        # First two calls fail, third succeeds
                        mock_sync_execute.side_effect = [
                            Exception("ClickHouse error"),
                            Exception("ClickHouse error"),
                            [],
                        ]

                        mock_redis = Mock()
                        mock_redis.get.return_value = None
                        mock_get_client.return_value = mock_redis

                        result = await activity_environment.client.execute_workflow(
                            SyncFeatureFlagLastCalledWorkflow.run,
                            inputs,
                            id=str(uuid.uuid4()),
                            task_queue=settings.TEMPORAL_TASK_QUEUE,
                        )

                        # Should succeed after retries
                        assert isinstance(result, FlagSyncResult)
                        assert result.updated_count == 0
                        assert result.processed_events == 0


class TestClickHouseQueryPerformance:
    @pytest.mark.django_db
    def test_clickhouse_query_structure(self, activity_environment, team):
        """Test ClickHouse query structure and parameters."""
        inputs = SyncFeatureFlagLastCalledInputs()

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis
                mock_sync_execute.return_value = []

                activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Verify query structure
                assert mock_sync_execute.call_count == 1
                call_args = mock_sync_execute.call_args
                query = call_args[0][0]
                params = call_args[0][1]

                # Check query contains expected elements
                assert "$feature_flag_called" in query
                assert "JSONExtractString(properties, '$feature_flag')" in query
                assert "max(timestamp)" in query
                assert "GROUP BY team_id, flag_key" in query

                # Check parameters
                assert "last_sync_timestamp" in params
                assert "current_sync_timestamp" in params


class TestRedisCheckpointPersistence:
    @pytest.mark.django_db
    def test_checkpoint_storage_and_retrieval(self, activity_environment, team):
        """Test Redis checkpoint storage and retrieval."""
        inputs = SyncFeatureFlagLastCalledInputs()

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                stored_checkpoint = None

                def mock_set(key, value):
                    nonlocal stored_checkpoint
                    stored_checkpoint = value

                def mock_get(key):
                    return stored_checkpoint.encode() if stored_checkpoint else None

                mock_redis.set.side_effect = mock_set
                mock_redis.get.side_effect = mock_get
                mock_get_client.return_value = mock_redis
                mock_sync_execute.return_value = []

                # First run - no checkpoint
                activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Verify checkpoint was stored
                assert stored_checkpoint is not None
                first_checkpoint = stored_checkpoint

                # Second run - with checkpoint
                activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Verify checkpoint was updated
                assert stored_checkpoint != first_checkpoint


class TestConcurrentSyncHandling:
    @pytest.mark.django_db
    def test_concurrent_flag_updates(self, activity_environment, team):
        """Test handling of concurrent updates to the same flag."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create flag with initial timestamp
        initial_timestamp = django_timezone.now() - timedelta(hours=1)
        flag = FeatureFlag.objects.create(
            team=team, key="test-flag", name="Test Flag", last_called_at=initial_timestamp
        )

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Simulate newer timestamp from ClickHouse
                newer_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, "test-flag", newer_timestamp, 5)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                assert result.updated_count == 1

                # Verify flag was updated to newer timestamp
                flag.refresh_from_db()
                assert flag.last_called_at.replace(microsecond=0) == newer_timestamp.replace(microsecond=0)


class TestDatabaseErrorRecovery:
    @pytest.mark.django_db
    def test_activity_database_error_handling(self, activity_environment, team):
        """Test handling of database connection errors during bulk_update."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create a flag to update
        FeatureFlag.objects.create(team=team, key="test-flag", name="Test Flag")

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                with patch("posthog.temporal.feature_flag_sync.workflow.capture_exception") as mock_capture:
                    mock_redis = Mock()
                    mock_redis.get.return_value = None
                    mock_get_client.return_value = mock_redis

                    # Mock ClickHouse result
                    new_timestamp = django_timezone.now()
                    mock_sync_execute.return_value = [(team.id, "test-flag", new_timestamp, 5)]

                    # Mock database error during bulk_update
                    with patch("posthog.models.feature_flag.feature_flag.FeatureFlag.objects.bulk_update") as mock_bulk:
                        from django.db import DatabaseError

                        mock_bulk.side_effect = DatabaseError("Connection lost")

                        result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                        # Should complete without raising exception
                        assert result.updated_count == 0  # No flags updated due to error
                        assert result.processed_events == 5  # Events were still processed
                        assert result.sync_duration_seconds > 0

                        # Verify error was captured with context
                        mock_capture.assert_called_once()
                        call_args = mock_capture.call_args
                        assert isinstance(call_args[0][0], DatabaseError)
                        assert call_args[1]["extra"]["flags_count"] == 1

                        # Verify Redis checkpoint was still updated
                        mock_redis.set.assert_called_once()
                        call_args = mock_redis.set.call_args[0]
                        assert call_args[0] == FEATURE_FLAG_LAST_CALLED_SYNC_KEY

    @pytest.mark.django_db
    def test_activity_partial_database_failure(self, activity_environment, team):
        """Test handling when bulk_update partially fails."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create multiple flags
        flags = []
        for i in range(3):
            flag = FeatureFlag.objects.create(team=team, key=f"test-flag-{i}", name=f"Test Flag {i}")
            flags.append(flag)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                with patch("posthog.temporal.feature_flag_sync.workflow.capture_exception") as mock_capture:
                    mock_redis = Mock()
                    mock_redis.get.return_value = None
                    mock_get_client.return_value = mock_redis

                    # Mock ClickHouse result for all flags
                    new_timestamp = django_timezone.now()
                    mock_sync_execute.return_value = [
                        (team.id, "test-flag-0", new_timestamp, 2),
                        (team.id, "test-flag-1", new_timestamp, 3),
                        (team.id, "test-flag-2", new_timestamp, 4),
                    ]

                    # Mock database error during bulk_update
                    with patch("posthog.models.feature_flag.feature_flag.FeatureFlag.objects.bulk_update") as mock_bulk:
                        from django.db import IntegrityError

                        mock_bulk.side_effect = IntegrityError("Constraint violation")

                        result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                        # Should handle error gracefully
                        assert result.updated_count == 0  # No updates due to error
                        assert result.processed_events == 9  # 2+3+4 events still counted

                        # Verify error was captured
                        mock_capture.assert_called_once()
                        call_args = mock_capture.call_args
                        assert isinstance(call_args[0][0], IntegrityError)
                        assert call_args[1]["extra"]["flags_count"] == 3

    @pytest.mark.django_db
    def test_activity_database_timeout_handling(self, activity_environment, team):
        """Test handling of database timeout errors."""
        inputs = SyncFeatureFlagLastCalledInputs()

        FeatureFlag.objects.create(team=team, key="test-flag", name="Test Flag")

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                with patch("posthog.temporal.feature_flag_sync.workflow.capture_exception") as mock_capture:
                    mock_redis = Mock()
                    mock_redis.get.return_value = None
                    mock_get_client.return_value = mock_redis

                    new_timestamp = django_timezone.now()
                    mock_sync_execute.return_value = [(team.id, "test-flag", new_timestamp, 1)]

                    # Mock database timeout
                    with patch("posthog.models.feature_flag.feature_flag.FeatureFlag.objects.bulk_update") as mock_bulk:
                        from django.db import OperationalError

                        mock_bulk.side_effect = OperationalError("Query timeout")

                        result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                        # Should handle timeout gracefully
                        assert result.updated_count == 0
                        assert result.processed_events == 1

                        # Verify error context includes timeout details
                        mock_capture.assert_called_once()
                        error_call = mock_capture.call_args
                        assert isinstance(error_call[0][0], OperationalError)
                        assert "Query timeout" in str(error_call[0][0])

    @pytest.mark.django_db
    def test_activity_database_error_preserves_redis_state(self, activity_environment, team):
        """Test that Redis checkpoint is still updated even when database fails."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Setup existing checkpoint
        last_sync = django_timezone.now() - timedelta(hours=1)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                with patch("posthog.temporal.feature_flag_sync.workflow.capture_exception"):
                    mock_redis = Mock()
                    mock_redis.get.return_value = last_sync.isoformat().encode()
                    mock_get_client.return_value = mock_redis

                    # Mock ClickHouse has results
                    current_time = django_timezone.now()
                    mock_sync_execute.return_value = [(team.id, "test-flag", current_time, 1)]

                    # Mock database failure
                    with patch("posthog.models.feature_flag.feature_flag.FeatureFlag.objects.bulk_update") as mock_bulk:
                        from django.db import DatabaseError

                        mock_bulk.side_effect = DatabaseError("Connection failed")

                        activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                        # Verify Redis checkpoint was still updated with current timestamp
                        mock_redis.set.assert_called_once()
                        set_call = mock_redis.set.call_args[0]
                        assert set_call[0] == FEATURE_FLAG_LAST_CALLED_SYNC_KEY

                        # Checkpoint should be updated to current time, not the failed sync time
                        stored_timestamp = django_timezone.datetime.fromisoformat(set_call[1])
                        assert stored_timestamp > last_sync


class TestBatchSizeHandling:
    @pytest.mark.django_db
    def test_activity_batch_size_exactly_1000(self, activity_environment, team):
        """Test bulk_update with exactly 1000 flags (batch boundary)."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create exactly 1000 flags
        flags = []
        for i in range(1000):
            flag = FeatureFlag.objects.create(team=team, key=f"test-flag-{i}", name=f"Test Flag {i}")
            flags.append(flag)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse result for all 1000 flags
                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, f"test-flag-{i}", new_timestamp, 1) for i in range(1000)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # All 1000 flags should be updated in a single batch
                assert result.updated_count == 1000
                assert result.processed_events == 1000

                # Verify all flags were actually updated
                updated_flags = FeatureFlag.objects.filter(team=team, last_called_at__isnull=False)
                assert updated_flags.count() == 1000

    @pytest.mark.django_db
    def test_activity_batch_size_1001_flags(self, activity_environment, team):
        """Test bulk_update with 1001 flags (exceeds single batch)."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create 1001 flags
        flags = []
        for i in range(1001):
            flag = FeatureFlag.objects.create(team=team, key=f"test-flag-{i}", name=f"Test Flag {i}")
            flags.append(flag)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse result for all 1001 flags
                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, f"test-flag-{i}", new_timestamp, 1) for i in range(1001)]

                with patch("posthog.models.feature_flag.feature_flag.FeatureFlag.objects.bulk_update") as mock_bulk:
                    result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                    # Should still update all flags despite exceeding batch size
                    assert result.updated_count == 1001
                    assert result.processed_events == 1001

                    # Verify bulk_update was called with correct batch_size parameter
                    mock_bulk.assert_called_once()
                    call_args = mock_bulk.call_args
                    assert call_args[1]["batch_size"] == 1000  # Verify batch_size parameter

    @pytest.mark.django_db
    def test_activity_large_dataset_stress_test(self, activity_environment, team):
        """Test bulk_update with large dataset (2500 flags)."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create 2500 flags to test multiple batches
        flags = []
        for i in range(2500):
            flag = FeatureFlag.objects.create(team=team, key=f"test-flag-{i}", name=f"Test Flag {i}")
            flags.append(flag)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse result for all 2500 flags
                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, f"test-flag-{i}", new_timestamp, 2) for i in range(2500)]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should handle large dataset efficiently
                assert result.updated_count == 2500
                assert result.processed_events == 5000  # 2500 flags * 2 events each

                # Verify all flags were updated
                updated_flags = FeatureFlag.objects.filter(team=team, last_called_at__isnull=False)
                assert updated_flags.count() == 2500

    @pytest.mark.django_db
    def test_activity_batch_processing_with_mixed_teams(self, activity_environment, team):
        """Test batch processing when flags span multiple teams."""
        from posthog.models import Team

        inputs = SyncFeatureFlagLastCalledInputs()

        # Create second team
        team2 = Team.objects.create(organization=team.organization, name="Test Team 2")

        # Create flags across multiple teams (1200 total)
        flags = []
        for i in range(600):
            flag1 = FeatureFlag.objects.create(team=team, key=f"team1-flag-{i}", name=f"Team1 Flag {i}")
            flag2 = FeatureFlag.objects.create(team=team2, key=f"team2-flag-{i}", name=f"Team2 Flag {i}")
            flags.extend([flag1, flag2])

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse result for flags from both teams
                new_timestamp = django_timezone.now()
                clickhouse_results = []
                for i in range(600):
                    clickhouse_results.append((team.id, f"team1-flag-{i}", new_timestamp, 1))
                    clickhouse_results.append((team2.id, f"team2-flag-{i}", new_timestamp, 1))

                mock_sync_execute.return_value = clickhouse_results

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should update flags from both teams
                assert result.updated_count == 1200
                assert result.processed_events == 1200

                # Verify flags from both teams were updated
                team1_updated = FeatureFlag.objects.filter(team=team, last_called_at__isnull=False)
                team2_updated = FeatureFlag.objects.filter(team=team2, last_called_at__isnull=False)
                assert team1_updated.count() == 600
                assert team2_updated.count() == 600

        # Cleanup
        team2.delete()

    @pytest.mark.django_db
    def test_activity_empty_batch_handling(self, activity_environment, team):
        """Test bulk_update behavior with empty flag list."""
        inputs = SyncFeatureFlagLastCalledInputs()

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse result for non-existent flags
                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [(team.id, "non-existent-flag", new_timestamp, 5)]

                with patch("posthog.models.feature_flag.feature_flag.FeatureFlag.objects.bulk_update") as mock_bulk:
                    result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                    # Should handle empty update list gracefully
                    assert result.updated_count == 0
                    assert result.processed_events == 5

                    # bulk_update should not be called with empty list
                    mock_bulk.assert_not_called()


class TestPartialBulkUpdateFailures:
    @pytest.mark.django_db
    def test_activity_handles_concurrent_flag_deletion(self, activity_environment, team):
        """Test handling when flags are deleted between ClickHouse query and bulk update."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create flags
        flag1 = FeatureFlag.objects.create(team=team, key="flag-to-keep", name="Flag to Keep")
        FeatureFlag.objects.create(team=team, key="flag-to-delete", name="Flag to Delete")

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # Mock ClickHouse returns result for deleted flag and existing flag
                new_timestamp = django_timezone.now()
                mock_sync_execute.return_value = [
                    (team.id, "flag-to-keep", new_timestamp, 3),
                    (team.id, "deleted-flag", new_timestamp, 2),  # Flag doesn't exist in DB
                ]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should only update the flag that exists
                assert result.updated_count == 1
                assert result.processed_events == 5

                # Verify the existing flag was updated
                flag1.refresh_from_db()
                assert flag1.last_called_at is not None

    @pytest.mark.django_db
    def test_activity_handles_flags_with_newer_timestamps(self, activity_environment, team):
        """Test partial update scenario where some flags already have newer timestamps."""
        inputs = SyncFeatureFlagLastCalledInputs()

        # Create flags with different timestamp states
        old_time = django_timezone.now() - timedelta(hours=3)
        recent_time = django_timezone.now() - timedelta(minutes=5)

        flag1 = FeatureFlag.objects.create(team=team, key="old-flag", name="Old Flag", last_called_at=old_time)
        flag2 = FeatureFlag.objects.create(team=team, key="recent-flag", name="Recent Flag", last_called_at=recent_time)
        flag3 = FeatureFlag.objects.create(team=team, key="null-flag", name="Null Flag", last_called_at=None)

        with patch("posthog.temporal.feature_flag_sync.workflow.sync_execute") as mock_sync_execute:
            with patch("posthog.temporal.feature_flag_sync.workflow.get_client") as mock_get_client:
                mock_redis = Mock()
                mock_redis.get.return_value = None
                mock_get_client.return_value = mock_redis

                # ClickHouse returns timestamp between old and recent
                middle_time = django_timezone.now() - timedelta(hours=1)
                mock_sync_execute.return_value = [
                    (team.id, "old-flag", middle_time, 2),  # Should update (newer than old_time)
                    (team.id, "recent-flag", middle_time, 3),  # Should NOT update (older than recent_time)
                    (team.id, "null-flag", middle_time, 1),  # Should update (was null)
                ]

                result = activity_environment.run(sync_feature_flag_last_called_activity, inputs)

                # Should only update 2 out of 3 flags
                assert result.updated_count == 2
                assert result.processed_events == 6

                # Verify correct flags were updated
                flag1.refresh_from_db()
                flag2.refresh_from_db()
                flag3.refresh_from_db()

                assert flag1.last_called_at.replace(microsecond=0) == middle_time.replace(microsecond=0)
                assert flag2.last_called_at.replace(microsecond=0) == recent_time.replace(microsecond=0)  # Unchanged
                assert flag3.last_called_at.replace(microsecond=0) == middle_time.replace(microsecond=0)
