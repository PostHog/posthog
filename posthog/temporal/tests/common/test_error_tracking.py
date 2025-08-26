"""Test that we capture exceptions in activities and workflows to PostHog."""

import uuid
import datetime as dt
from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import patch

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.posthog_client import PostHogClientInterceptor


@dataclass
class OptionallyFailingInputs:
    fail: bool


@workflow.defn
class OptionallyFailingWorkflow:
    @workflow.run
    async def run(self, inputs: OptionallyFailingInputs) -> None:
        await workflow.execute_activity(
            failing_activity,
            OptionallyFailingInputs(fail=inputs.fail),
            # Setting a timeout is required.
            start_to_close_timeout=dt.timedelta(minutes=1),
            heartbeat_timeout=dt.timedelta(seconds=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=1),
                maximum_interval=dt.timedelta(seconds=1),
                maximum_attempts=1,
            ),
        )


@activity.defn
async def failing_activity(inputs: OptionallyFailingInputs) -> None:
    if inputs.fail:
        raise ValueError("Activity failed!")


@dataclass
class OptionallyFailingInputsWithPropertiesToLog:
    fail: bool

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"fail": self.fail}


@workflow.defn
class OptionallyFailingWorkflowWithPropertiesToLog:
    @workflow.run
    async def run(self, inputs: OptionallyFailingInputsWithPropertiesToLog) -> None:
        await workflow.execute_activity(
            failing_activity_with_properties_to_log,
            OptionallyFailingInputsWithPropertiesToLog(fail=inputs.fail),
            # Setting a timeout is required.
            start_to_close_timeout=dt.timedelta(minutes=1),
            heartbeat_timeout=dt.timedelta(seconds=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=1),
                maximum_interval=dt.timedelta(seconds=1),
                maximum_attempts=1,
            ),
        )


@activity.defn
async def failing_activity_with_properties_to_log(inputs: OptionallyFailingInputsWithPropertiesToLog) -> None:
    if inputs.fail:
        raise ValueError("Activity failed!")


@pytest.mark.parametrize("fail", [True, False])
@pytest.mark.parametrize("capture_additional_properties", [True, False])
@pytest.mark.asyncio
async def test_exception_capture(fail: bool, capture_additional_properties: bool, temporal_client: Client):
    if not fail and capture_additional_properties:
        # skip unnecessary test
        pytest.skip("Skipping test because fail is False and capture_additional_properties is True")

    task_queue = "TEST-TASK-QUEUE"
    workflow_id = str(uuid.uuid4())

    if capture_additional_properties:
        workflow = "OptionallyFailingWorkflowWithPropertiesToLog"
        workflow_inputs = OptionallyFailingInputsWithPropertiesToLog(fail=fail)
    else:
        workflow = "OptionallyFailingWorkflow"
        workflow_inputs = OptionallyFailingInputs(fail=fail)

    with (
        patch("posthog.temporal.common.posthog_client.capture_exception") as mock_ph_capture,
    ):
        async with Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[OptionallyFailingWorkflow, OptionallyFailingWorkflowWithPropertiesToLog],
            activities=[failing_activity, failing_activity_with_properties_to_log],
            interceptors=[PostHogClientInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            if fail:
                with pytest.raises(WorkflowFailureError):
                    await temporal_client.execute_workflow(
                        workflow,
                        workflow_inputs,
                        id=workflow_id,
                        task_queue=task_queue,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
            else:
                await temporal_client.execute_workflow(
                    workflow,
                    workflow_inputs,
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        if fail:
            # Verify capture_exception was called with correct properties
            assert mock_ph_capture.call_count == 2  # Once for activity, once for workflow

            # Verify activity exception capture
            activity_call = mock_ph_capture.call_args_list[0]
            assert isinstance(activity_call[0][0], ValueError)
            assert activity_call[1]["properties"]["temporal.execution_type"] == "activity"
            assert activity_call[1]["properties"]["temporal.workflow.id"] == workflow_id
            if capture_additional_properties:
                assert activity_call[1]["properties"]["fail"] == fail
            else:
                assert "fail" not in activity_call[1]["properties"]

            # Verify workflow exception capture
            workflow_call = mock_ph_capture.call_args_list[1]
            assert isinstance(workflow_call[0][0], ActivityError)
            assert workflow_call[1]["properties"]["temporal.execution_type"] == "workflow"
            assert workflow_call[1]["properties"]["temporal.workflow.id"] == workflow_id
            if capture_additional_properties:
                assert workflow_call[1]["properties"]["fail"] == fail
            else:
                assert "fail" not in workflow_call[1]["properties"]

        else:
            mock_ph_capture.assert_not_called()
