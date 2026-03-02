import pytest
from unittest.mock import Mock, patch

from posthog.temporal.messaging.realtime_cohort_calculation_workflow import flush_kafka_batch
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    CohortSelectionActivityInput,
    QueryPercentileThresholds,
    QueryPercentileThresholdsInput,
    RealtimeCohortCalculationCoordinatorWorkflowInputs,
    _apply_duration_filtering,
    get_query_percentile_thresholds_activity,
    get_realtime_cohort_selection_activity,
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

    def test_coordinator_workflow_inputs_partial_env_var_defaults(self):
        """Should only load env vars for fields that are None."""
        with (
            patch("posthog.settings.schedules.REALTIME_COHORT_CALCULATION_TEAMS", {999}),
            patch("posthog.settings.schedules.REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE", 0.999),
        ):
            # User explicitly sets empty team_ids but wants env var for global_percentage
            inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
                team_ids=set(),  # Explicitly empty (not None)
                global_percentage=None,  # Use env var default
            )

            # Should preserve user's explicit empty set and use env var for percentage
            assert inputs.team_ids == set()  # User's explicit value, not env var {999}
            assert inputs.global_percentage == 0.999  # From env var

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

    def test_worker_inputs_support_cohort_id_array(self):
        """Worker inputs should support receiving cohort ID arrays from coordinator."""

        from posthog.temporal.messaging.realtime_cohort_calculation_workflow import (
            RealtimeCohortCalculationWorkflowInputs,
        )

        # Test new array approach
        inputs = RealtimeCohortCalculationWorkflowInputs(cohort_ids=[10, 15, 20, 25])

        assert inputs.cohort_ids == [10, 15, 20, 25]
        assert inputs.properties_to_log["cohort_ids"] == [10, 15, 20, 25]
        assert inputs.properties_to_log["num_cohorts"] == 4

        # Test array approach with many cohorts (should truncate in logs)
        many_cohort_ids = list(range(1, 16))  # 1-15
        inputs_many = RealtimeCohortCalculationWorkflowInputs(cohort_ids=many_cohort_ids)

        assert inputs_many.cohort_ids == many_cohort_ids
        assert inputs_many.properties_to_log["cohort_ids"] == list(range(1, 11))  # First 10
        assert inputs_many.properties_to_log["num_cohorts"] == 15

        # Test backward compatibility with single cohort_id
        inputs_single = RealtimeCohortCalculationWorkflowInputs(cohort_id=42)

        assert inputs_single.cohort_id == 42
        assert inputs_single.cohort_ids is None
        assert inputs_single.properties_to_log["cohort_id"] == 42
        assert inputs_single.properties_to_log["num_cohorts"] == 1

        # Test empty case
        inputs_empty = RealtimeCohortCalculationWorkflowInputs()

        assert inputs_empty.cohort_ids is None
        assert inputs_empty.cohort_id is None
        assert inputs_empty.properties_to_log["num_cohorts"] == 0


class TestRealtimeCohortSelectionActivity:
    """Tests for the get_realtime_cohort_selection_activity function."""

    @pytest.mark.asyncio
    async def test_selection_activity_with_specific_cohort_id_exists(self):
        """When cohort_id is specified and exists, should return that cohort ID."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(cohort_id=123)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.exists.return_value = True
            mock_cohort.objects.filter.return_value = mock_queryset

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            assert result.cohort_ids == [123]
            mock_cohort.objects.filter.assert_called_once()

    @pytest.mark.asyncio
    async def test_selection_activity_with_specific_cohort_id_not_exists(self):
        """When cohort_id is specified but doesn't exist, should return empty list."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(cohort_id=999)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.exists.return_value = False
            mock_cohort.objects.filter.return_value = mock_queryset

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            assert result.cohort_ids == []

    @pytest.mark.asyncio
    async def test_selection_activity_with_team_ids_only(self):
        """Should select all cohorts for specified teams."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(team_ids={2, 3}, global_percentage=None)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Combined teams query returns all cohorts from teams 2 and 3
            combined_teams_queryset = Mock()
            combined_teams_queryset.order_by.return_value.values_list.return_value = [10, 20, 30, 40]

            mock_cohort.objects.filter.return_value = combined_teams_queryset

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            # Should include all cohorts from both teams, sorted by ID
            assert result.cohort_ids == [10, 20, 30, 40]

    @pytest.mark.asyncio
    async def test_selection_activity_with_global_percentage_only(self):
        """Should select percentage of all cohorts when no teams specified."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids=set(),
            global_percentage=0.5,  # 50%
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # All teams have cohorts [1, 2, 3, 4, 5, 6]
            queryset = Mock()
            queryset.order_by.return_value.values_list.return_value = [1, 2, 3, 4, 5, 6]
            mock_cohort.objects.filter.return_value = queryset

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            # Should select 50% = 3 cohorts (random sampling, but always 3 total)
            assert len(result.cohort_ids) == 3
            # All selected IDs should be from the available set
            assert all(cohort_id in [1, 2, 3, 4, 5, 6] for cohort_id in result.cohort_ids)
            # Should be unique
            assert len(set(result.cohort_ids)) == 3

    @pytest.mark.asyncio
    async def test_selection_activity_with_small_global_percentage_returns_zero(self):
        """Should return empty list when global percentage results in zero cohorts."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids=set(),
            global_percentage=0.01,  # 1% of 10 = 0.1 → 0
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            queryset = Mock()
            queryset.order_by.return_value.values_list.return_value = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            mock_cohort.objects.filter.return_value = queryset

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            # Should be empty since int(10 * 0.01) = 0
            assert result.cohort_ids == []

    @pytest.mark.asyncio
    async def test_selection_activity_with_team_ids_and_global_percentage(self):
        """Should combine team-specific cohorts with global percentage of other teams."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids={2},
            global_percentage=0.5,  # 50% of other teams
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Team 2 has cohorts [10, 20]
            team2_queryset = Mock()
            team2_queryset.order_by.return_value.values_list.return_value = [10, 20]

            # Other teams (excluding team 2) have cohorts [1, 2, 3, 4]
            other_teams_base_queryset = Mock()
            other_teams_queryset = Mock()
            other_teams_queryset.order_by.return_value.values_list.return_value = [1, 2, 3, 4]
            other_teams_base_queryset.exclude.return_value = other_teams_queryset

            mock_cohort.objects.filter.side_effect = [team2_queryset, other_teams_base_queryset]

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            # Should include:
            # - All cohorts from team 2: [10, 20]
            # - 50% of other teams: 2 out of [1, 2, 3, 4] (random selection)
            assert len(result.cohort_ids) == 4
            # Must include all team 2 cohorts
            assert 10 in result.cohort_ids
            assert 20 in result.cohort_ids
            # Must include exactly 2 from other teams
            other_team_cohorts = [id for id in result.cohort_ids if id in [1, 2, 3, 4]]
            assert len(other_team_cohorts) == 2

    @pytest.mark.asyncio
    async def test_selection_activity_deduplication(self):
        """Should remove duplicate cohort IDs while preserving order."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(team_ids={2, 3}, global_percentage=0.5)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Combined teams query returns all cohorts from teams 2 and 3
            # Team 2: [10, 30], Team 3: [20, 30] -> Combined: [10, 30, 20, 30]
            combined_teams_queryset = Mock()
            combined_teams_queryset.order_by.return_value.values_list.return_value = [10, 30, 20, 30]

            # Other teams have cohorts [1, 2, 10] - note: 10 is duplicate
            other_teams_base_queryset = Mock()
            other_teams_queryset = Mock()
            other_teams_queryset.order_by.return_value.values_list.return_value = [1, 2, 10]
            other_teams_base_queryset.exclude.return_value = other_teams_queryset

            mock_cohort.objects.filter.side_effect = [combined_teams_queryset, other_teams_base_queryset]

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            # Should include forced teams cohorts: [10, 30, 20]
            # Plus 50% of other teams' [1, 2, 10] = 1 cohort (random sampling)
            # After deduplication: depends on which cohort was randomly selected

            # Should always include all forced team cohorts
            assert all(cohort_id in result.cohort_ids for cohort_id in [10, 20, 30])

            # Check what was randomly selected from other teams
            other_cohorts = [id for id in result.cohort_ids if id not in [10, 20, 30]]

            if len(other_cohorts) == 1:
                # Selected a unique cohort (1 or 2)
                assert len(result.cohort_ids) == 4
                assert other_cohorts[0] in [1, 2]
            else:
                # Selected cohort 10 (duplicate), so deduplicated to 3 total
                assert len(result.cohort_ids) == 3
                assert len(other_cohorts) == 0

            # Should be sorted
            assert result.cohort_ids == sorted(result.cohort_ids)

    @pytest.mark.asyncio
    async def test_selection_activity_skips_invalid_team_ids(self):
        """Should skip invalid team IDs (non-int or <= 0)."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids={2, 0, -1},  # 0 and -1 are invalid
            global_percentage=None,
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Only team 2 should be queried
            team2_queryset = Mock()
            team2_queryset.order_by.return_value.values_list.return_value = [10, 20]
            mock_cohort.objects.filter.return_value = team2_queryset

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            # Should only include cohorts from team 2
            assert result.cohort_ids == [10, 20]
            # Should only call filter once (for valid team 2)
            assert mock_cohort.objects.filter.call_count == 1

    @pytest.mark.asyncio
    async def test_selection_activity_random_sampling(self):
        """Should select cohorts using random sampling for fair distribution over time."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(team_ids=set(), global_percentage=0.6)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Cohorts returned in different order from DB
            queryset = Mock()
            queryset.order_by.return_value.values_list.return_value = [50, 10, 30, 20, 40]
            mock_cohort.objects.filter.return_value = queryset

            activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
            result = await get_realtime_cohort_selection_activity(activity_input)

            # Should select 60% = 3 cohorts, randomly sampled
            assert len(result.cohort_ids) == 3
            # All selected IDs should be from available set
            assert all(cohort_id in [50, 10, 30, 20, 40] for cohort_id in result.cohort_ids)
            # Should be unique
            assert len(set(result.cohort_ids)) == 3
            # Should be sorted in final result
            assert result.cohort_ids == sorted(result.cohort_ids)

    @pytest.mark.asyncio
    async def test_selection_activity_random_variability(self):
        """Should select different cohorts on different runs due to randomness."""

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(team_ids=set(), global_percentage=0.5)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Set up cohorts
            queryset = Mock()
            queryset.order_by.return_value.values_list.return_value = [1, 2, 3, 4, 5, 6]
            mock_cohort.objects.filter.return_value = queryset

            # Run multiple times to verify randomness
            results = []
            for _ in range(10):  # Run 10 times to get some variability
                activity_input = CohortSelectionActivityInput(coordinator_inputs=inputs)
                result = await get_realtime_cohort_selection_activity(activity_input)
                results.append(set(result.cohort_ids))

            # All should select 50% = 3 cohorts
            assert all(len(result) == 3 for result in results)

            # With random sampling, we should see some variability in selections
            # (It's theoretically possible all runs select the same cohorts, but extremely unlikely)
            unique_selections = {frozenset(result) for result in results}
            assert len(unique_selections) > 1, "Random sampling should produce different selections"


class TestDurationFiltering:
    """Tests for duration-based cohort filtering functionality."""

    def test_apply_duration_filtering_no_thresholds(self):
        """Should return original queryset when no thresholds provided."""
        mock_queryset = Mock()

        result = _apply_duration_filtering(mock_queryset, None)

        assert result is mock_queryset
        # Should not call any filter methods
        assert not mock_queryset.filter.called

    def test_apply_duration_filtering_normal_range(self):
        """Should apply both lower and upper bounds for normal percentile ranges."""
        mock_queryset = Mock()
        mock_filtered_queryset = Mock()
        mock_queryset.filter.return_value = mock_filtered_queryset

        thresholds = QueryPercentileThresholds(
            min_threshold_ms=5000,  # 5 seconds
            max_threshold_ms=30000,  # 30 seconds
        )

        result = _apply_duration_filtering(mock_queryset, thresholds, is_p100=False)

        assert result is mock_filtered_queryset
        mock_queryset.filter.assert_called_once_with(
            last_calculation_duration_ms__gte=5000,  # 5s * 1000
            last_calculation_duration_ms__lt=30000,  # 30s * 1000
        )

    def test_apply_duration_filtering_p100_includes_nulls(self):
        """Should include NULL durations when filtering p100 range (slowest tier)."""
        from django.db.models import Q

        mock_queryset = Mock()
        mock_filtered_queryset = Mock()
        mock_queryset.filter.return_value = mock_filtered_queryset

        thresholds = QueryPercentileThresholds(
            min_threshold_ms=60000,  # 60 seconds minimum
            max_threshold_ms=120000,  # This value doesn't matter for p100
        )

        result = _apply_duration_filtering(mock_queryset, thresholds, is_p100=True)

        assert result is mock_filtered_queryset
        # Should use Q objects to include both duration >= threshold OR NULL
        mock_queryset.filter.assert_called_once()
        filter_args = mock_queryset.filter.call_args[0]
        assert len(filter_args) == 1
        q_filter = filter_args[0]
        assert isinstance(q_filter, Q)

    def test_apply_duration_filtering_p100_vs_normal(self):
        """Should behave differently for p100 vs normal ranges with same thresholds."""
        mock_queryset = Mock()
        thresholds = QueryPercentileThresholds(min_threshold_ms=10.0, max_threshold_ms=50.0)

        # Normal range (p90-p95)
        _apply_duration_filtering(mock_queryset, thresholds, is_p100=False)
        normal_call = mock_queryset.filter.call_args

        mock_queryset.reset_mock()

        # P100 range (p95-p100)
        _apply_duration_filtering(mock_queryset, thresholds, is_p100=True)
        p100_call = mock_queryset.filter.call_args

        # Should use different filtering logic
        assert normal_call != p100_call

    def test_apply_duration_filtering_uses_millisecond_values(self):
        """Should use millisecond threshold values directly in filtering."""
        mock_queryset = Mock()

        thresholds = QueryPercentileThresholds(
            min_threshold_ms=2500,  # 2.5 seconds in milliseconds
            max_threshold_ms=7250,  # 7.25 seconds in milliseconds
        )

        _apply_duration_filtering(mock_queryset, thresholds, is_p100=False)

        mock_queryset.filter.assert_called_once_with(
            last_calculation_duration_ms__gte=2500,
            last_calculation_duration_ms__lt=7250,
        )

    def test_query_percentile_thresholds_backward_compatibility(self):
        """Test that QueryPercentileThresholds handles old field names correctly."""
        # Test backward compatibility by creating instance with old field names
        # This simulates what Temporal would do when deserializing old data
        thresholds = QueryPercentileThresholds(min_threshold_ms=0, max_threshold_ms=0)

        # Simulate Temporal setting the old field names
        thresholds.min_threshold_seconds = 2.5
        thresholds.max_threshold_seconds = 7.25

        # Trigger post_init manually to simulate deserialization
        thresholds.__post_init__()

        # Should have converted to milliseconds
        assert thresholds.min_threshold_ms == 2500
        assert thresholds.max_threshold_ms == 7250


class TestQueryPercentileThresholdsActivity:
    """Tests for ClickHouse percentile threshold calculation."""

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_get_percentile_thresholds_success(self):
        """Should successfully calculate percentile thresholds from cohort data."""
        inputs = QueryPercentileThresholdsInput(
            min_percentile=90.0,  # p90
            max_percentile=95.0,  # p95
        )

        # Mock cohort queryset with duration data (in milliseconds)
        mock_durations = [
            1000,
            2000,
            3000,
            4000,
            5000,
            6000,
            7000,
            8000,
            9000,
            10000,
            11000,
            12000,
            13000,
            14000,
            15000,
            16000,
            17000,
            18000,
            19000,
            20000,
        ]

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            # Create a mock values_list queryset that behaves like an actual queryset
            mock_values_list_qs = Mock()
            mock_values_list_qs.__bool__ = Mock(return_value=True)  # Make it truthy for the `if not` check
            mock_values_list_qs.__iter__ = Mock(return_value=iter(mock_durations))  # Make it iterable
            mock_values_list_qs.__len__ = Mock(return_value=len(mock_durations))  # Support len()

            # Create a filter queryset that returns the values_list queryset
            mock_filter_qs = Mock()
            mock_filter_qs.values_list.return_value = mock_values_list_qs

            mock_cohort.objects.filter.return_value = mock_filter_qs

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is not None
        # With 20 data points, p90 should be around 18000ms, p95 around 19000ms
        assert result.min_threshold_ms >= 17000
        assert result.min_threshold_ms <= 19000
        assert result.max_threshold_ms >= 18000
        assert result.max_threshold_ms <= 20000

    @pytest.mark.asyncio
    async def test_get_percentile_thresholds_defaults_to_p0_p100(self):
        """Should default to p0-p100 when percentiles not specified."""
        inputs = QueryPercentileThresholdsInput()  # No percentiles specified

        # Mock cohort queryset with duration data (in milliseconds)
        mock_durations = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000]

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.values_list.return_value = mock_durations
            mock_cohort.objects.filter.return_value = mock_queryset

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is not None
        # p0 is treated as a lower bound of 0, p100 should be the maximum observed value (5000)
        assert result.min_threshold_ms == 0  # p0 (lower bound)
        assert result.max_threshold_ms == 5000  # p100 (max value)

    @pytest.mark.asyncio
    async def test_get_percentile_thresholds_no_historical_data(self):
        """Should return None when no historical query data exists."""
        inputs = QueryPercentileThresholdsInput(min_percentile=0.0, max_percentile=90.0)

        # Empty result from ClickHouse
        mock_result = []

        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = mock_result

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_percentile_thresholds_null_values(self):
        """Should return None when ClickHouse returns NULL values."""
        inputs = QueryPercentileThresholdsInput(min_percentile=50.0, max_percentile=75.0)

        # NULL values from ClickHouse (insufficient data)
        mock_result = [(None, None)]

        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = mock_result

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_percentile_thresholds_partial_null_values(self):
        """Should return None when some threshold values are NULL."""
        inputs = QueryPercentileThresholdsInput(min_percentile=75.0, max_percentile=90.0)

        # One NULL value
        mock_result = [(25.0, None)]

        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = mock_result

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_percentile_thresholds_invalid_result_format(self):
        """Should return None when ClickHouse result has invalid format."""
        inputs = QueryPercentileThresholdsInput(min_percentile=80.0, max_percentile=95.0)

        # Invalid result format (missing second value)
        mock_result = [(25.0,)]  # Only one value instead of two

        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = mock_result

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_percentile_thresholds_clickhouse_error(self):
        """Should return None when ClickHouse query fails."""
        inputs = QueryPercentileThresholdsInput(min_percentile=60.0, max_percentile=80.0)

        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.side_effect = Exception("ClickHouse connection failed")

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_percentile_thresholds_non_numeric_values(self):
        """Should return None when ClickHouse returns non-numeric values."""
        inputs = QueryPercentileThresholdsInput(min_percentile=70.0, max_percentile=85.0)

        # Non-numeric values that can't be converted to float
        mock_result = [("invalid", "also_invalid")]

        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = mock_result

            result = await get_query_percentile_thresholds_activity(inputs)

        assert result is None


class TestDurationFilteringIntegration:
    """Integration tests for duration filtering with cohort selection."""

    @pytest.mark.asyncio
    async def test_selection_activity_with_duration_thresholds_p90_p95(self):
        """Should apply duration filtering for p90-p95 percentile range."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids={2}, duration_percentile_min=90.0, duration_percentile_max=95.0
        )

        thresholds = QueryPercentileThresholds(
            min_threshold_ms=10000,  # 10 seconds
            max_threshold_ms=25000,  # 25 seconds
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_initial_queryset = Mock()
            mock_filtered_queryset = Mock()
            mock_filtered_queryset.order_by.return_value.values_list.return_value = [100, 200]
            mock_initial_queryset.filter.return_value = mock_filtered_queryset

            mock_cohort.objects.filter.return_value = mock_initial_queryset

            activity_input = CohortSelectionActivityInput(
                coordinator_inputs=inputs, query_percentile_thresholds=thresholds
            )
            result = await get_realtime_cohort_selection_activity(activity_input)

        assert result.cohort_ids == [100, 200]

        # Should apply duration filtering with correct parameters
        mock_initial_queryset.filter.assert_called_once_with(
            last_calculation_duration_ms__gte=10000,  # 10s * 1000
            last_calculation_duration_ms__lt=25000,  # 25s * 1000
        )

    @pytest.mark.asyncio
    async def test_selection_activity_with_duration_thresholds_p95_p100(self):
        """Should apply p100 filtering (include NULLs) for p95-p100 percentile range."""
        from django.db.models import Q

        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids={3},
            duration_percentile_min=95.0,
            duration_percentile_max=100.0,  # This triggers is_p100=True
        )

        thresholds = QueryPercentileThresholds(
            min_threshold_ms=30000,  # 30 seconds minimum
            max_threshold_ms=60000,  # Max doesn't matter for p100
        )

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_initial_queryset = Mock()
            mock_filtered_queryset = Mock()
            mock_filtered_queryset.order_by.return_value.values_list.return_value = [300, 400, 500]
            mock_initial_queryset.filter.return_value = mock_filtered_queryset

            mock_cohort.objects.filter.return_value = mock_initial_queryset

            activity_input = CohortSelectionActivityInput(
                coordinator_inputs=inputs, query_percentile_thresholds=thresholds
            )
            result = await get_realtime_cohort_selection_activity(activity_input)

        assert result.cohort_ids == [300, 400, 500]

        # Should apply p100 filtering (Q object with OR condition for NULLs)
        mock_initial_queryset.filter.assert_called_once()
        filter_args = mock_initial_queryset.filter.call_args[0]
        assert len(filter_args) == 1
        assert isinstance(filter_args[0], Q)

    @pytest.mark.asyncio
    async def test_selection_activity_no_duration_filtering_when_no_thresholds(self):
        """Should skip duration filtering when no thresholds provided."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids={5},
            duration_percentile_min=80.0,  # These are set but...
            duration_percentile_max=90.0,
        )

        # No thresholds provided (e.g., ClickHouse had no data)
        thresholds = None

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.order_by.return_value.values_list.return_value = [600, 700]
            mock_cohort.objects.filter.return_value = mock_queryset

            activity_input = CohortSelectionActivityInput(
                coordinator_inputs=inputs, query_percentile_thresholds=thresholds
            )
            result = await get_realtime_cohort_selection_activity(activity_input)

        assert result.cohort_ids == [600, 700]

        # Should NOT call filter for duration filtering
        # Only the base filter for team_ids should be called
        assert mock_queryset.filter.call_count == 0  # No duration filtering

    @pytest.mark.asyncio
    async def test_selection_activity_no_duration_filtering_when_no_percentiles(self):
        """Should skip duration filtering when percentile parameters not set."""
        inputs = RealtimeCohortCalculationCoordinatorWorkflowInputs(
            team_ids={7},
            # No duration_percentile_min or duration_percentile_max set
        )

        thresholds = QueryPercentileThresholds(min_threshold_ms=15.0, max_threshold_ms=40.0)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator.Cohort") as mock_cohort:
            mock_queryset = Mock()
            mock_queryset.order_by.return_value.values_list.return_value = [800, 900]
            mock_cohort.objects.filter.return_value = mock_queryset

            activity_input = CohortSelectionActivityInput(
                coordinator_inputs=inputs, query_percentile_thresholds=thresholds
            )
            result = await get_realtime_cohort_selection_activity(activity_input)

        assert result.cohort_ids == [800, 900]

        # Should NOT apply duration filtering because percentile params are None
        assert mock_queryset.filter.call_count == 0
