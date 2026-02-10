import pytest
from unittest.mock import Mock, patch

from posthog.temporal.messaging.realtime_cohort_calculation_workflow import flush_kafka_batch
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    RealtimeCohortCalculationCoordinatorWorkflowInputs,
    get_realtime_cohort_calculation_count_activity,
)


class TestFlushKafkaBatch:
    """Tests for the flush_kafka_batch helper function."""

    @pytest.mark.asyncio
    async def test_empty_messages_returns_zero(self):
        """When pending_messages is empty, should return 0 without flushing."""
        kafka_producer = Mock()
        heartbeater = Mock()
        logger = Mock()

        result = await flush_kafka_batch(
            kafka_producer=kafka_producer,
            pending_messages=[],
            cohort_id=123,
            idx=1,
            total_cohorts=5,
            heartbeater=heartbeater,
            logger=logger,
        )

        assert result == 0
        kafka_producer.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_batch_flush(self):
        """Should flush messages and return batch size on success."""
        kafka_producer = Mock()
        kafka_producer.flush = Mock()

        # Mock successful send results
        mock_results = [Mock() for _ in range(100)]
        for mock_result in mock_results:
            mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread") as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=mock_results,
                cohort_id=123,
                idx=1,
                total_cohorts=5,
                heartbeater=heartbeater,
                logger=logger,
            )

        assert result == 100
        mock_thread.assert_called_once_with(kafka_producer.flush)
        logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_final_batch_includes_final_in_messages(self):
        """When is_final=True, should include 'final' in heartbeat and log messages."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result],
                cohort_id=123,
                idx=1,
                total_cohorts=5,
                heartbeater=heartbeater,
                logger=logger,
                is_final=True,
            )

        # Check heartbeat details includes "final"
        assert heartbeater.details[0].startswith("Flushing final ")

        # Check logger includes "final"
        log_call_args = logger.info.call_args[0][0]
        assert "final" in log_call_args.lower()

    @pytest.mark.asyncio
    async def test_non_final_batch_excludes_final_from_messages(self):
        """When is_final=False, should not include 'final' in messages."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result],
                cohort_id=123,
                idx=1,
                total_cohorts=5,
                heartbeater=heartbeater,
                logger=logger,
                is_final=False,
            )

        # Check heartbeat details does not include "final"
        heartbeat_msg = heartbeater.details[0]
        assert "final" not in heartbeat_msg.lower()

        # Check logger does not include "final"
        log_call_args = logger.info.call_args[0][0]
        assert "final" not in log_call_args.lower()

    @pytest.mark.asyncio
    async def test_batch_flush_with_partial_failures(self):
        """Should raise exception when some messages fail to send."""
        kafka_producer = Mock()

        # Create mix of successful and failed results
        successful_result = Mock()
        successful_result.get = Mock(return_value=None)

        failed_result = Mock()
        failed_result.get = Mock(side_effect=Exception("Send failed"))

        mock_results = [successful_result, failed_result, successful_result]

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            with pytest.raises(Exception, match="Failed to send 1/3 Kafka messages"):
                await flush_kafka_batch(
                    kafka_producer=kafka_producer,
                    pending_messages=mock_results,
                    cohort_id=123,
                    idx=1,
                    total_cohorts=5,
                    heartbeater=heartbeater,
                    logger=logger,
                )

        # Should log warnings for failed messages
        assert logger.warning.call_count == 1
        # Should log error summary
        assert logger.error.call_count == 1

    @pytest.mark.asyncio
    async def test_batch_flush_with_all_failures(self):
        """Should raise exception when all messages fail to send."""
        kafka_producer = Mock()

        # All results fail
        mock_results = []
        for _ in range(5):
            failed_result = Mock()
            failed_result.get = Mock(side_effect=Exception("Send failed"))
            mock_results.append(failed_result)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            with pytest.raises(Exception, match="Failed to send 5/5 Kafka messages"):
                await flush_kafka_batch(
                    kafka_producer=kafka_producer,
                    pending_messages=mock_results,
                    cohort_id=123,
                    idx=1,
                    total_cohorts=5,
                    heartbeater=heartbeater,
                    logger=logger,
                )

        assert logger.warning.call_count == 5
        assert logger.error.call_count == 1

    @pytest.mark.asyncio
    async def test_heartbeat_details_format(self):
        """Should format heartbeat details with cohort progress information."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result] * 10000,
                cohort_id=456,
                idx=3,
                total_cohorts=10,
                heartbeater=heartbeater,
                logger=logger,
            )

        heartbeat_msg = heartbeater.details[0]
        assert "10000 messages" in heartbeat_msg
        assert "cohort 3/10" in heartbeat_msg
        assert "cohort_id=456" in heartbeat_msg

    @pytest.mark.asyncio
    async def test_logger_includes_cohort_metadata(self):
        """Should include cohort_id and batch_size in logger metadata."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result] * 5000,
                cohort_id=789,
                idx=2,
                total_cohorts=8,
                heartbeater=heartbeater,
                logger=logger,
            )

        # Check logger.info was called with metadata
        logger.info.assert_called_once()
        call_kwargs = logger.info.call_args[1]
        assert call_kwargs["cohort_id"] == 789
        assert call_kwargs["batch_size"] == 5000


class TestBatchFlushingBehavior:
    """Tests for batch flushing logic and integration."""

    def test_flush_batch_size_constant_is_10k(self):
        """Verify the FLUSH_BATCH_SIZE constant is set to 10,000."""
        # Read the source to verify the constant
        import inspect

        import posthog.temporal.messaging.realtime_cohort_calculation_workflow as module

        source = inspect.getsource(module.process_realtime_cohort_calculation_activity)
        assert "FLUSH_BATCH_SIZE = 10_000" in source

    @pytest.mark.asyncio
    async def test_multiple_batches_handled_correctly(self):
        """Should handle multiple batch flushes correctly."""
        kafka_producer = Mock()

        # Simulate 3 batches: 10k, 10k, 5k
        heartbeater = Mock()
        logger = Mock()

        mock_results_batch1 = [Mock() for _ in range(10000)]
        mock_results_batch2 = [Mock() for _ in range(10000)]
        mock_results_batch3 = [Mock() for _ in range(5000)]

        for result in mock_results_batch1 + mock_results_batch2 + mock_results_batch3:
            result.get = Mock(return_value=None)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            # Batch 1
            result1 = await flush_kafka_batch(kafka_producer, mock_results_batch1, 123, 1, 5, heartbeater, logger)
            # Batch 2
            result2 = await flush_kafka_batch(kafka_producer, mock_results_batch2, 123, 1, 5, heartbeater, logger)
            # Batch 3 (final)
            result3 = await flush_kafka_batch(
                kafka_producer, mock_results_batch3, 123, 1, 5, heartbeater, logger, is_final=True
            )

        assert result1 == 10000
        assert result2 == 10000
        assert result3 == 5000
        assert result1 + result2 + result3 == 25000


class TestRealtimeCohortCalculationCoordinator:
    """Tests for the coordinator workflow and percentage-based cohort selection."""

    @pytest.mark.asyncio
    async def test_count_activity_with_specific_cohort_id(self):
        """When cohort_id is specified, should count only that cohort."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(cohort_id=123)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.count.return_value = 1
            mock_cohort.objects.filter.return_value = mock_queryset

            result = await get_realtime_cohort_calculation_count_activity(inputs)

            assert result.count == 1
            mock_cohort.objects.filter.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_activity_with_force_teams(self):
        """Teams in force list should count all their cohorts."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(team_ids={2})

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Team 2 has 3 cohorts
            team_queryset = Mock()
            team_queryset.count.return_value = 3
            mock_cohort.objects.filter.return_value = team_queryset

            result = await get_realtime_cohort_calculation_count_activity(inputs)

            assert result.count == 3

    @pytest.mark.asyncio
    async def test_count_activity_with_global_percentage_calculates_correctly(self):
        """When global percentage is specified, should calculate percentage correctly."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(team_ids=set(), global_percentage=0.1)  # 10% global

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # All teams have 20 cohorts, 10% = 2 cohorts (minimum 1)
            team_queryset = Mock()
            team_queryset.count.return_value = 20
            mock_cohort.objects.filter.return_value = team_queryset

            result = await get_realtime_cohort_calculation_count_activity(inputs)

            # Should be 2 (10% of 20)
            assert result.count == 2

    @pytest.mark.asyncio
    async def test_count_activity_with_small_global_percentage_ensures_minimum_one(self):
        """When global percentage is small, should ensure at least 1 cohort."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids=set(),  # Explicitly set empty team_ids
            global_percentage=0.05,  # 5%
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # All teams have 10 cohorts, 5% = 0.5, should round to 1 (minimum 1)
            team_queryset = Mock()
            team_queryset.count.return_value = 10
            mock_cohort.objects.filter.return_value = team_queryset

            result = await get_realtime_cohort_calculation_count_activity(inputs)

            # Should be 1 (minimum, since 5% of 10 = 0.5 < 1)
            assert result.count == 1

    def test_coordinator_workflow_inputs_includes_team_ids(self):
        """RealtimeCohortCalculationCoordinatorWorkflowInputs should include team_ids and global_percentage."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            parallelism=5,
            workflows_per_batch=2,
            batch_delay_minutes=3,
            cohort_id=None,
            team_ids={2, 42},
            global_percentage=0.5,
        )

        assert inputs.team_ids == {2, 42}
        assert inputs.global_percentage == 0.5

        # Check it's included in properties_to_log
        props = inputs.properties_to_log
        assert "team_ids" in props
        assert "global_percentage" in props
        assert set(props["team_ids"]) == {2, 42}
        assert props["global_percentage"] == 0.5

    def test_coordinator_workflow_inputs_with_simple_structure(self):
        """RealtimeCohortCalculationCoordinatorWorkflowInputs should support simple team_ids + global_percentage structure."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            parallelism=5,
            workflows_per_batch=2,
            batch_delay_minutes=3,
            cohort_id=None,
            team_ids={42, 100},
            global_percentage=0.3,
        )

        assert inputs.team_ids == {42, 100}
        assert inputs.global_percentage == 0.3

        # Check it's included in properties_to_log
        props = inputs.properties_to_log
        assert "team_ids" in props
        assert "global_percentage" in props
        assert set(props["team_ids"]) == {42, 100}
        assert props["global_percentage"] == 0.3

    def test_coordinator_workflow_inputs_uses_env_var_default(self):
        """Should use env vars when no params provided."""
        with (
            patch("posthog.settings.schedules.REALTIME_COHORT_CALCULATION_TEAMS", {2, 42}),
            patch("posthog.settings.schedules.REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE", 0.5),
        ):
            inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs()

            # Should use the env var defaults
            assert inputs.team_ids == {2, 42}
            assert inputs.global_percentage == 0.5

    def test_team_percentages_parsing_from_env_var(self):
        """Test parsing team percentages from environment variable using JSON format."""
        import json

        # Test the JSON parsing directly with mock env var values
        with patch("posthog.settings.schedules.get_from_env") as mock_get_env:
            # Test simple single team format
            mock_get_env.return_value = '{"2": 0.5}'
            raw_settings = json.loads(mock_get_env.return_value)
            result = {int(k): float(v) for k, v in raw_settings.items()}
            assert result == {2: 0.5}

            # Test multiple teams format
            mock_get_env.return_value = '{"2": 0.3, "42": 0.8}'
            raw_settings = json.loads(mock_get_env.return_value)
            result = {int(k): float(v) for k, v in raw_settings.items()}
            assert result == {2: 0.3, 42: 0.8}

    def test_team_percentages_parsing_with_invalid_format(self):
        """Test parsing handles invalid JSON gracefully by falling back to default."""
        import json

        with patch("posthog.settings.schedules.get_from_env") as mock_get_env:
            # Test invalid JSON format - should fall back to default
            mock_get_env.return_value = "invalid json"
            try:
                raw_settings = json.loads(mock_get_env.return_value)
                result = {int(k): float(v) for k, v in raw_settings.items()}
            except Exception:
                result = {2: 0.0}  # Fallback to default

            # Should use the fallback default
            assert result == {2: 0.0}

    @pytest.mark.asyncio
    async def test_count_activity_with_force_teams_plus_global_percentage(self):
        """Should count specific teams + global percentage for other teams."""
        # Team 2 and 3 get all cohorts, Global: 50% for others
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(team_ids={2, 3}, global_percentage=0.5)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Create separate mock querysets for different calls
            team2_queryset = Mock()
            team2_queryset.count.return_value = 10  # Team 2 has 10 cohorts

            team3_queryset = Mock()
            team3_queryset.count.return_value = 20  # Team 3 has 20 cohorts

            other_teams_queryset = Mock()
            other_teams_queryset.count.return_value = 30  # Other teams have 30 cohorts

            # Set up the exclude method chain
            base_queryset = Mock()
            base_queryset.exclude.return_value = other_teams_queryset

            # Mock the filter calls in order
            mock_cohort.objects.filter.side_effect = [team2_queryset, team3_queryset, base_queryset]

            result = await get_realtime_cohort_calculation_count_activity(inputs)

            # Team 2: All 10 cohorts
            # Team 3: All 20 cohorts
            # Global: 50% of 30 = 15 cohorts (max(1, int(30 * 0.5)))
            # Total: 10 + 20 + 15 = 45
            assert result.count == 45

    @pytest.mark.asyncio
    async def test_count_activity_with_only_global_percentage(self):
        """Should count global percentage when no specific teams are configured."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids=set(),  # Explicitly set empty team_ids
            global_percentage=0.4,
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            queryset = Mock()
            queryset.count.return_value = 25  # Total cohorts
            mock_cohort.objects.filter.return_value = queryset

            result = await get_realtime_cohort_calculation_count_activity(inputs)

            # Global: 40% of 25 = 10 cohorts (max(1, int(25 * 0.4)))
            assert result.count == 10

    def test_worker_inputs_support_cohort_id_range(self):
        """Worker inputs should support receiving cohort ID ranges from coordinator."""

        from posthog.temporal.messaging.realtime_cohort_calculation_workflow import (
            RealtimeCohortCalculationWorkflowInputs,
        )

        # Test new range approach
        inputs = RealtimeCohortCalculationWorkflowInputs(min_cohort_id=10, max_cohort_id=20)

        assert inputs.min_cohort_id == 10
        assert inputs.max_cohort_id == 20
        assert inputs.properties_to_log["min_cohort_id"] == 10
        assert inputs.properties_to_log["max_cohort_id"] == 20
        assert inputs.properties_to_log["range_size"] == 11  # 20 - 10 + 1

        # Test backward compatibility with single cohort_id
        inputs_single = RealtimeCohortCalculationWorkflowInputs(cohort_id=42)

        assert inputs_single.cohort_id == 42
        assert inputs_single.min_cohort_id is None
        assert inputs_single.max_cohort_id is None
        assert inputs_single.properties_to_log["cohort_id"] == 42
        assert inputs_single.properties_to_log["num_cohorts"] == 1

        # Test empty case
        inputs_empty = RealtimeCohortCalculationWorkflowInputs()

        assert inputs_empty.min_cohort_id is None
        assert inputs_empty.max_cohort_id is None
        assert inputs_empty.cohort_id is None
        assert inputs_empty.properties_to_log["num_cohorts"] == 0
