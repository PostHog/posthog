"""Test that we capture exceptions in activities and workflows to PostHog."""

import uuid
import datetime as dt
import dataclasses
from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import patch

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.posthog_client import PostHogClientInterceptor, _activity_failure_will_retry


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


@workflow.defn
class DirectlyFailingWorkflow:
    @workflow.run
    async def run(self, inputs: OptionallyFailingInputs) -> None:
        if inputs.fail:
            raise ApplicationError("Workflow failed!")


@pytest.mark.parametrize("fail", [True, False])
@pytest.mark.parametrize("capture_additional_properties", [True, False])
@pytest.mark.asyncio
async def test_exception_capture(fail: bool, capture_additional_properties: bool, temporal_client: Client):
    if not fail and capture_additional_properties:
        pytest.skip("Skipping test because fail is False and capture_additional_properties is True")

    task_queue = "TEST-TASK-QUEUE"
    workflow_id = str(uuid.uuid4())

    if capture_additional_properties:
        workflow_name = "OptionallyFailingWorkflowWithPropertiesToLog"
        workflow_inputs: OptionallyFailingInputs | OptionallyFailingInputsWithPropertiesToLog = (
            OptionallyFailingInputsWithPropertiesToLog(fail=fail)
        )
    else:
        workflow_name = "OptionallyFailingWorkflow"
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
                        workflow_name,
                        workflow_inputs,
                        id=workflow_id,
                        task_queue=task_queue,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
            else:
                await temporal_client.execute_workflow(
                    workflow_name,
                    workflow_inputs,
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        if fail:
            assert mock_ph_capture.call_count == 1

            activity_call = mock_ph_capture.call_args_list[0]
            captured_exc = activity_call[0][0]
            assert isinstance(captured_exc, ValueError)
            assert captured_exc.__traceback__ is not None
            assert activity_call[1]["properties"]["temporal.execution_type"] == "activity"
            assert activity_call[1]["properties"]["temporal.workflow.id"] == workflow_id
            if capture_additional_properties:
                assert activity_call[1]["properties"]["fail"] == fail
            else:
                assert "fail" not in activity_call[1]["properties"]

            from posthoganalytics.exception_utils import exceptions_from_error_tuple

            exc_info = (type(captured_exc), captured_exc, captured_exc.__traceback__)
            formatted = exceptions_from_error_tuple(exc_info)
            assert len(formatted) > 0
            assert formatted[0].get("stacktrace", {}).get("frames")

        else:
            mock_ph_capture.assert_not_called()


@pytest.mark.parametrize(
    "attempt,retry_policy,exc,expected_will_retry",
    [
        # Bounded retries with attempts remaining: defer capture, Temporal will retry.
        (1, RetryPolicy(maximum_attempts=3), ValueError("boom"), True),
        (2, RetryPolicy(maximum_attempts=3), ValueError("boom"), True),
        # Bounded retries on the final attempt: terminal, capture now.
        (3, RetryPolicy(maximum_attempts=3), ValueError("boom"), False),
        # Retries disabled: every failure is terminal.
        (1, RetryPolicy(maximum_attempts=1), ValueError("boom"), False),
        # Unlimited retries: no final attempt to wait for, so capture now.
        (5, RetryPolicy(maximum_attempts=0), ValueError("boom"), False),
        # Server didn't report a retry policy: can't defer, capture now.
        (1, None, ValueError("boom"), False),
        # Non-retryable application error is terminal even mid-retry.
        (1, RetryPolicy(maximum_attempts=3), ApplicationError("boom", non_retryable=True), False),
        # Error type excluded from retries is terminal even mid-retry.
        (1, RetryPolicy(maximum_attempts=3, non_retryable_error_types=["ValueError"]), ValueError("boom"), False),
    ],
)
def test_activity_failure_will_retry(
    attempt: int, retry_policy: RetryPolicy | None, exc: Exception, expected_will_retry: bool
):
    info = dataclasses.replace(ActivityEnvironment.default_info(), attempt=attempt, retry_policy=retry_policy)
    assert _activity_failure_will_retry(exc, info) is expected_will_retry


@pytest.mark.asyncio
async def test_workflow_only_error_is_captured(temporal_client: Client):
    task_queue = "TEST-TASK-QUEUE"
    workflow_id = str(uuid.uuid4())

    with patch("posthog.temporal.common.posthog_client.capture_exception") as mock_ph_capture:
        async with Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[DirectlyFailingWorkflow],
            activities=[],
            interceptors=[PostHogClientInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await temporal_client.execute_workflow(
                    "DirectlyFailingWorkflow",
                    OptionallyFailingInputs(fail=True),
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        assert mock_ph_capture.call_count == 1
        workflow_call = mock_ph_capture.call_args_list[0]
        assert isinstance(workflow_call[0][0], ApplicationError)
        assert workflow_call[1]["properties"]["temporal.execution_type"] == "workflow"
        assert workflow_call[1]["properties"]["temporal.workflow.id"] == workflow_id
