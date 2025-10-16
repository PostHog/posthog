import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator import (
    BehavioralCohortsCoordinatorWorkflow,
    ConditionsCountResult,
    CoordinatorWorkflowInputs,
    RunningWorkflowsResult,
    check_running_workflows_activity,
    get_conditions_count_activity,
)


class TestBehavioralCohortsCoordinatorWorkflow:
    class MockAsyncIterator:
        """Reusable async iterator mock for tests."""

        def __init__(self, items):
            self.items = iter(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.items)
            except StopIteration:
                raise StopAsyncIteration

    def _setup_workflow_check_test(self, workflows=None, exception=None):
        """Setup common test infrastructure for workflow checking tests."""
        inputs = CoordinatorWorkflowInputs()
        mock_client = MagicMock()

        if exception:
            mock_client.list_workflows.side_effect = exception
        else:
            mock_workflow_iter = self.MockAsyncIterator(workflows or [])
            mock_client.list_workflows.return_value = mock_workflow_iter

        return inputs, mock_client

    @pytest.mark.asyncio
    async def test_check_running_workflows_activity_with_running_workflows(self):
        """Test that check_running_workflows_activity correctly detects running workflows."""
        mock_workflow = MagicMock()
        mock_workflow.id = "test-workflow-1"

        inputs, mock_client = self._setup_workflow_check_test(workflows=[mock_workflow])

        with patch(
            "posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator.async_connect"
        ) as mock_async_connect:
            mock_async_connect.return_value = mock_client
            result = await check_running_workflows_activity(inputs)

        assert isinstance(result, RunningWorkflowsResult)
        assert result.has_running_workflows is True
        mock_client.list_workflows.assert_called_once_with(
            query="WorkflowType = 'behavioral-cohorts-analysis' AND ExecutionStatus = 'Running'"
        )

    @pytest.mark.asyncio
    async def test_check_running_workflows_activity_with_no_running_workflows(self):
        """Test that check_running_workflows_activity correctly detects when no workflows are running."""
        inputs, mock_client = self._setup_workflow_check_test(workflows=[])

        with patch(
            "posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator.async_connect"
        ) as mock_async_connect:
            mock_async_connect.return_value = mock_client
            result = await check_running_workflows_activity(inputs)

        assert isinstance(result, RunningWorkflowsResult)
        assert result.has_running_workflows is False
        mock_client.list_workflows.assert_called_once_with(
            query="WorkflowType = 'behavioral-cohorts-analysis' AND ExecutionStatus = 'Running'"
        )

    @pytest.mark.asyncio
    async def test_check_running_workflows_activity_handles_exceptions(self):
        """Test that check_running_workflows_activity properly handles exceptions."""
        inputs, mock_client = self._setup_workflow_check_test(exception=Exception("Connection error"))

        with patch(
            "posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator.async_connect"
        ) as mock_async_connect:
            mock_async_connect.return_value = mock_client
            with pytest.raises(Exception, match="Connection error"):
                await check_running_workflows_activity(inputs)

    @pytest.mark.asyncio
    async def test_coordinator_behavior_exits_early_when_workflows_running(self):
        """Test coordinator calls the right APIs and exits early when workflows are running."""
        inputs = CoordinatorWorkflowInputs(parallelism=3, team_id=123)

        # Mock Temporal APIs
        with (
            patch("temporalio.workflow.execute_activity") as mock_execute_activity,
            patch("temporalio.workflow.logger"),
        ):
            # Setup: running workflows found
            mock_execute_activity.return_value = RunningWorkflowsResult(has_running_workflows=True)

            # Run the actual coordinator logic
            coordinator = BehavioralCohortsCoordinatorWorkflow()
            await coordinator.run(inputs)

            # Verify API calls: only check for running workflows, nothing else
            mock_execute_activity.assert_called_once_with(
                check_running_workflows_activity,
                inputs,
                start_to_close_timeout=mock_execute_activity.call_args[1]["start_to_close_timeout"],
                retry_policy=mock_execute_activity.call_args[1]["retry_policy"],
            )

    @pytest.mark.asyncio
    async def test_coordinator_behavior_full_flow_creates_correct_child_workflows(self):
        """Test coordinator calls correct APIs and creates child workflows with right parameters."""
        inputs = CoordinatorWorkflowInputs(parallelism=3, team_id=123, min_matches=5)

        with (
            patch("temporalio.workflow.execute_activity") as mock_execute_activity,
            patch("temporalio.workflow.start_child_workflow") as mock_start_child,
            patch("temporalio.workflow.logger"),
            patch("temporalio.workflow.info") as mock_info,
        ):
            # Setup responses
            mock_execute_activity.side_effect = [
                RunningWorkflowsResult(has_running_workflows=False),  # No running workflows
                ConditionsCountResult(count=100),  # 100 conditions found
            ]
            mock_info.return_value = MagicMock(workflow_id="coordinator-123")

            # Run the actual coordinator
            coordinator = BehavioralCohortsCoordinatorWorkflow()
            await coordinator.run(inputs)

            # Verify activity calls
            assert mock_execute_activity.call_count == 2
            mock_execute_activity.assert_any_call(
                check_running_workflows_activity,
                inputs,
                start_to_close_timeout=mock_execute_activity.call_args_list[0][1]["start_to_close_timeout"],
                retry_policy=mock_execute_activity.call_args_list[0][1]["retry_policy"],
            )
            mock_execute_activity.assert_any_call(
                get_conditions_count_activity,
                inputs,
                start_to_close_timeout=mock_execute_activity.call_args_list[1][1]["start_to_close_timeout"],
                retry_policy=mock_execute_activity.call_args_list[1][1]["retry_policy"],
            )

            # Verify child workflow calls - this tests the ACTUAL parallelism logic
            assert mock_start_child.call_count == 3  # parallelism=3

            # Verify the actual distribution logic by checking what the coordinator calculated
            child_calls = mock_start_child.call_args_list

            # Child 0: offset=0, limit=34 (100/3 = 33.33, ceil = 34)
            child_0_inputs = child_calls[0][0][1]  # Second argument is inputs
            assert child_0_inputs.team_id == 123
            assert child_0_inputs.min_matches == 5
            assert child_0_inputs.offset == 0
            assert child_0_inputs.limit == 34

            # Child 1: offset=34, limit=34
            child_1_inputs = child_calls[1][0][1]
            assert child_1_inputs.offset == 34
            assert child_1_inputs.limit == 34

            # Child 2: offset=68, limit=32 (remaining)
            child_2_inputs = child_calls[2][0][1]
            assert child_2_inputs.offset == 68
            assert child_2_inputs.limit == 32

    @pytest.mark.asyncio
    async def test_coordinator_behavior_no_conditions_skips_child_workflows(self):
        """Test coordinator handles zero conditions correctly."""
        inputs = CoordinatorWorkflowInputs(parallelism=5)

        with (
            patch("temporalio.workflow.execute_activity") as mock_execute_activity,
            patch("temporalio.workflow.start_child_workflow") as mock_start_child,
            patch("temporalio.workflow.logger"),
        ):
            # Setup: no running workflows, but zero conditions
            mock_execute_activity.side_effect = [
                RunningWorkflowsResult(has_running_workflows=False),
                ConditionsCountResult(count=0),
            ]

            # Run coordinator
            coordinator = BehavioralCohortsCoordinatorWorkflow()
            await coordinator.run(inputs)

            # Verify behavior
            assert mock_execute_activity.call_count == 2  # Both activities called
            mock_start_child.assert_not_called()  # No child workflows created
