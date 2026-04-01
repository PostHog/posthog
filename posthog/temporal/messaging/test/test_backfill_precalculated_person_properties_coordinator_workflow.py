import pytest
from unittest.mock import Mock, patch

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
            "concurrent_workflows": 5,
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
    async def test_processes_ranges_with_concurrent_workflows(self):
        """Should discover ranges and start child workflows with concurrency limit."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1, 2],
            batch_size=100,
            concurrent_workflows=2,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-123"

        # Mock person ID ranges returned by activity - single range to keep it simple
        mock_ranges = [("person1", "person100")]

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        # Track child workflows started
        child_workflows_started = []

        # Mock the helper method instead of the complex asyncio logic
        async def mock_start_child_workflow(inputs_arg, logger, batch_num, start_id, end_id, handles):
            child_workflows_started.append(
                {
                    "batch_number": batch_num,
                    "start_person_id": start_id,
                    "end_person_id": end_id,
                }
            )

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_activity", return_value=mock_ranges),
            patch.object(workflow, "_start_child_workflow_for_range", side_effect=mock_start_child_workflow),
            patch("asyncio.wait", return_value=([], [])),  # No pending workflows
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            await workflow.run(inputs)

            # Should start child workflow for the range
            assert len(child_workflows_started) == 1
            assert child_workflows_started[0]["batch_number"] == 1
            assert child_workflows_started[0]["start_person_id"] == "person1"
            assert child_workflows_started[0]["end_person_id"] == "person100"

            # Should log successful completion
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("completed successfully" in call for call in log_calls)

    @pytest.mark.asyncio
    async def test_handles_no_person_ranges(self):
        """Should handle the case when no person ranges are found."""
        inputs = BackfillPrecalculatedPersonPropertiesCoordinatorInputs(
            team_id=123,
            filter_storage_key="test-key",
            cohort_ids=[1],
            batch_size=100,
            concurrent_workflows=2,
        )

        # Mock workflow info
        mock_workflow_info = Mock()
        mock_workflow_info.workflow_id = "test-coordinator-no-ranges"

        # Mock empty ranges
        mock_ranges: list[tuple[str, str]] = []

        workflow = BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow()

        with (
            patch("temporalio.workflow.info", return_value=mock_workflow_info),
            patch("temporalio.workflow.execute_activity", return_value=mock_ranges),
            patch("temporalio.workflow.logger") as mock_logger,
        ):
            # Should complete without error
            await workflow.run(inputs)

            # Should log that no persons were found
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            assert any("No persons found for team" in call for call in log_calls)
