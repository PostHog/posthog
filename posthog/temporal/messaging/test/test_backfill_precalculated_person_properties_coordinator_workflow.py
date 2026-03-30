import pytest
from unittest.mock import Mock, patch

import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
)
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesResult,
)


class TestBackfillPrecalculatedPersonPropertiesCoordinatorInputs:
    """Tests for the coordinator inputs dataclass."""

    def test_properties_to_log(self):
        """Should return all relevant properties for logging."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key-456",
            cohort_ids=[1, 2, 3],
            batch_size=500,
        )

        expected = {
            "team_id": 123,
            "cohort_count": 3,
            "cohort_ids": [1, 2, 3],
            "filter_storage_key": "test-key-456",
            "batch_size": 500,
        }

        assert inputs.properties_to_log == expected

    def test_default_batch_size(self):
        """Should default to 1000 batch size."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
        )

        assert inputs.batch_size == 1000


class TestBackfillPrecalculatedPersonPropertiesCoordinatorWorkflow:
    """Tests for the coordinator workflow."""

    def test_parse_inputs_raises_not_implemented(self):
        """Should raise NotImplementedError for CLI parsing."""
        with pytest.raises(NotImplementedError):
            BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow.parse_inputs(["arg1", "arg2"])

    @pytest.mark.asyncio
    async def test_normal_multi_batch_iteration(self):
        """Should process multiple batches sequentially until completion."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1, 2],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-123"

        # Mock child workflow results: 3 full batches, then partial batch
        batch_results = [
            BackfillPrecalculatedPersonPropertiesResult(
                persons_processed=100,
                events_produced=200,
                events_flushed=200,
                last_person_id="person-100",
                duration_seconds=10.0,
            ),
            BackfillPrecalculatedPersonPropertiesResult(
                persons_processed=100,
                events_produced=200,
                events_flushed=200,
                last_person_id="person-200",
                duration_seconds=10.0,
            ),
            BackfillPrecalculatedPersonPropertiesResult(
                persons_processed=100,
                events_produced=200,
                events_flushed=200,
                last_person_id="person-300",
                duration_seconds=10.0,
            ),
            BackfillPrecalculatedPersonPropertiesResult(
                persons_processed=50,  # Less than batch_size, indicating end
                events_produced=100,
                events_flushed=100,
                last_person_id="person-350",
                duration_seconds=5.0,
            ),
        ]

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", side_effect=batch_results) as mock_execute,
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            # Should have executed 4 child workflows
            assert mock_execute.call_count == 4

            # Verify child workflow calls with correct parameters
            expected_cursors = ["00000000-0000-0000-0000-000000000000", "person-100", "person-200", "person-300"]
            expected_child_ids = [
                "test-coordinator-123-batch-1",
                "test-coordinator-123-batch-2",
                "test-coordinator-123-batch-3",
                "test-coordinator-123-batch-4",
            ]

            for i, call in enumerate(mock_execute.call_args_list):
                args, kwargs = call

                # Check workflow name
                assert args[0] == "backfill-precalculated-person-properties"

                # Check inputs
                child_inputs = args[1]
                assert child_inputs.team_id == 123
                assert child_inputs.filter_storage_key == "test-key"
                assert child_inputs.cohort_ids == [1, 2]
                assert child_inputs.batch_size == 100
                assert child_inputs.cursor == expected_cursors[i]

                # Check kwargs
                assert kwargs["id"] == expected_child_ids[i]

            # Should log completion with total processed count
            completion_calls = [
                call for call in mock_logger.info.call_args_list if "Coordinator workflow completed" in str(call)
            ]
            assert len(completion_calls) == 1
            assert "Total persons processed: 350" in str(completion_calls[0])

    @pytest.mark.asyncio
    async def test_empty_dataset_handling(self):
        """Should handle empty dataset (first batch returns 0 persons)."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-empty"

        # Mock empty result from first batch
        empty_result = BackfillPrecalculatedPersonPropertiesResult(
            persons_processed=0,
            events_produced=0,
            events_flushed=0,
            last_person_id=None,
            duration_seconds=1.0,
        )

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", return_value=empty_result) as mock_execute,
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            # Should only execute one child workflow
            assert mock_execute.call_count == 1

            # Should log that no more persons to process
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("No more persons to process" in call for call in log_calls)
            assert any("Completed after 0 persons" in call for call in log_calls)

    @pytest.mark.asyncio
    async def test_single_batch_completion(self):
        """Should handle case where single batch completes all data."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=1000,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-single"

        # Mock result with fewer persons than batch size
        single_batch_result = BackfillPrecalculatedPersonPropertiesResult(
            persons_processed=500,  # Less than batch_size of 1000
            events_produced=1000,
            events_flushed=1000,
            last_person_id="person-500",
            duration_seconds=20.0,
        )

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", return_value=single_batch_result) as mock_execute,
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            # Should only execute one child workflow
            assert mock_execute.call_count == 1

            # Should log completion
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("Reached end of data" in call for call in log_calls)
            assert any("500 < 1000 batch size" in call for call in log_calls)
            assert any("Completed after 500 total persons" in call for call in log_calls)

    @pytest.mark.asyncio
    async def test_error_propagation_from_child_workflow(self):
        """Should propagate errors from child workflows."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-error"

        # Mock child workflow exception
        child_error = temporalio.exceptions.ApplicationError("Child workflow failed")

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", side_effect=child_error) as mock_execute,
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            with pytest.raises(temporalio.exceptions.ApplicationError) as exc_info:
                await workflow.run(inputs)

            assert str(exc_info.value) == "Child workflow failed"

            # Should execute child workflow once before failing
            assert mock_execute.call_count == 1

            # Should log the error
            error_calls = list(mock_logger.error.call_args_list)
            assert len(error_calls) == 1
            assert "Batch 1 failed" in str(error_calls[0])

    @pytest.mark.asyncio
    async def test_cursor_progression_verification(self):
        """Should correctly progress cursor between batches."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-cursor"

        # Mock results that demonstrate cursor progression
        batch_results = [
            BackfillPrecalculatedPersonPropertiesResult(
                persons_processed=100,
                events_produced=200,
                events_flushed=200,
                last_person_id="aaa-person-100",
                duration_seconds=10.0,
            ),
            BackfillPrecalculatedPersonPropertiesResult(
                persons_processed=100,
                events_produced=200,
                events_flushed=200,
                last_person_id="bbb-person-200",
                duration_seconds=10.0,
            ),
            BackfillPrecalculatedPersonPropertiesResult(
                persons_processed=50,  # End of data
                events_produced=100,
                events_flushed=100,
                last_person_id="ccc-person-250",
                duration_seconds=5.0,
            ),
        ]

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", side_effect=batch_results) as mock_execute,
            patch("temporalio.workflow.logger"),
        ):
            await workflow.run(inputs)

            # Verify cursor progression in child workflow calls
            calls = mock_execute.call_args_list
            assert len(calls) == 3

            # First batch starts with default cursor
            assert calls[0][0][1].cursor == "00000000-0000-0000-0000-000000000000"

            # Second batch uses last_person_id from first batch
            assert calls[1][0][1].cursor == "aaa-person-100"

            # Third batch uses last_person_id from second batch
            assert calls[2][0][1].cursor == "bbb-person-200"

    @pytest.mark.asyncio
    async def test_missing_last_person_id_handling(self):
        """Should handle case where last_person_id is None despite processing persons."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-missing-id"

        # Mock result with persons_processed > 0 but no last_person_id (shouldn't happen but handle safely)
        anomalous_result = BackfillPrecalculatedPersonPropertiesResult(
            persons_processed=100,
            events_produced=200,
            events_flushed=200,
            last_person_id=None,  # This shouldn't happen if persons_processed > 0
            duration_seconds=10.0,
        )

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", return_value=anomalous_result) as mock_execute,
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            # Should only execute one child workflow (stops safely)
            assert mock_execute.call_count == 1

            # Should log warning about missing last_person_id
            warning_calls = list(mock_logger.warning.call_args_list)
            assert len(warning_calls) == 1
            assert "No last_person_id returned despite processing persons" in str(warning_calls[0])

    @pytest.mark.asyncio
    async def test_dict_result_handling(self):
        """Should handle child workflow results that are dictionaries (from Temporal serialization)."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-dict"

        # Mock dictionary result (how Temporal sometimes returns results)
        dict_result = {
            "persons_processed": 50,
            "events_produced": 100,
            "events_flushed": 100,
            "last_person_id": "person-50",
            "duration_seconds": 5.0,
        }

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", return_value=dict_result) as mock_execute,
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            # Should handle the dict result and complete successfully
            assert mock_execute.call_count == 1

            # Should log completion with correct values from dict
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("processed 50 persons" in call for call in log_calls)
            assert any("last_person_id: person-50" in call for call in log_calls)

    @pytest.mark.asyncio
    async def test_child_workflow_configuration(self):
        """Should configure child workflows with correct settings."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1, 2, 3],
            batch_size=500,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-config"

        # Mock single result to test configuration
        result = BackfillPrecalculatedPersonPropertiesResult(
            persons_processed=0,
            events_produced=0,
            events_flushed=0,
            last_person_id=None,
            duration_seconds=1.0,
        )

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_child_workflow", return_value=result) as mock_execute,
            patch("temporalio.workflow.logger"),
            patch("django.conf.settings.MESSAGING_TASK_QUEUE", "test-messaging-queue"),
        ):
            await workflow.run(inputs)

            # Verify child workflow configuration
            args, kwargs = mock_execute.call_args

            # Check workflow name
            assert args[0] == "backfill-precalculated-person-properties"

            # Check child workflow options
            assert kwargs["id"] == "test-coordinator-config-batch-1"
            assert kwargs["task_queue"] == "test-messaging-queue"
            assert kwargs["parent_close_policy"] == temporalio.workflow.ParentClosePolicy.ABANDON
