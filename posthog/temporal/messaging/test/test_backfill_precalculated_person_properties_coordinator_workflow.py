import pytest
from unittest.mock import Mock, patch

import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorInputs,
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
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
    async def test_starts_first_workflow_only(self):
        """Should start only the first workflow in the pipeline."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1, 2],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-123"

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.start_child_workflow") as mock_start,
            patch("temporalio.workflow.logger") as mock_logger,
            patch("django.conf.settings.MESSAGING_TASK_QUEUE", "test-messaging-queue"),
        ):
            await workflow.run(inputs)

            # Should start exactly one child workflow
            assert mock_start.call_count == 1

            # Verify child workflow call with correct parameters
            args, kwargs = mock_start.call_args

            # Check workflow name
            assert args[0] == "backfill-precalculated-person-properties"

            # Check inputs
            child_inputs = args[1]
            assert child_inputs.team_id == 123
            assert child_inputs.filter_storage_key == "test-key"
            assert child_inputs.cohort_ids == [1, 2]
            assert child_inputs.batch_size == 100
            assert child_inputs.cursor == "00000000-0000-0000-0000-000000000000"
            assert child_inputs.batch_sequence == 1

            # Check workflow configuration
            assert kwargs["id"] == "test-coordinator-123-batch-1"
            assert kwargs["task_queue"] == "test-messaging-queue"
            assert kwargs["parent_close_policy"] == temporalio.workflow.ParentClosePolicy.ABANDON

            # Should log pipeline started
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("Pipeline started successfully" in call for call in log_calls)

    @pytest.mark.asyncio
    async def test_handles_startup_errors(self):
        """Should handle errors when starting the first workflow."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-error"

        # Mock startup error
        startup_error = Exception("Failed to start workflow")

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.start_child_workflow", side_effect=startup_error) as mock_start,
            patch("temporalio.workflow.logger") as mock_logger,
            patch("django.conf.settings.MESSAGING_TASK_QUEUE", "test-messaging-queue"),
        ):
            with pytest.raises(Exception) as exc_info:
                await workflow.run(inputs)

            assert str(exc_info.value) == "Failed to start workflow"

            # Should attempt to start workflow once
            assert mock_start.call_count == 1

            # Should log the error
            error_calls = list(mock_logger.error.call_args_list)
            assert len(error_calls) == 1
            assert "Failed to start initial batch" in str(error_calls[0])
