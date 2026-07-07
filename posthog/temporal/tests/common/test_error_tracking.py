"""Test that we capture exceptions in activities and workflows to PostHog."""

import uuid
import datetime as dt
from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import patch

import django.db

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, CancelledError
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


@activity.defn
async def cancelled_activity(inputs: OptionallyFailingInputs) -> None:
    raise CancelledError()


@workflow.defn
class CancelledActivityWorkflow:
    @workflow.run
    async def run(self, inputs: OptionallyFailingInputs) -> None:
        await workflow.execute_activity(
            cancelled_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            heartbeat_timeout=dt.timedelta(seconds=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


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


@pytest.mark.asyncio
async def test_cancellation_is_not_captured(temporal_client: Client):
    """A cancelled activity (worker drain, timeout, cancel) is expected control flow, not a defect,
    so the interceptor must re-raise without reporting it to error tracking."""
    task_queue = "TEST-TASK-QUEUE"
    workflow_id = str(uuid.uuid4())

    with patch("posthog.temporal.common.posthog_client.capture_exception") as mock_ph_capture:
        async with Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[CancelledActivityWorkflow],
            activities=[cancelled_activity],
            interceptors=[PostHogClientInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await temporal_client.execute_workflow(
                    "CancelledActivityWorkflow",
                    OptionallyFailingInputs(fail=True),
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        mock_ph_capture.assert_not_called()


@activity.defn
async def recovering_db_error_activity() -> None:
    # Transient connection drop that heals once retried on a fresh connection.
    if activity.info().attempt < 2:
        raise django.db.OperationalError("server closed the connection unexpectedly")


@activity.defn
async def persistent_db_error_activity() -> None:
    # Connection error that never recovers, exhausting the retry policy.
    raise django.db.OperationalError("server closed the connection unexpectedly")


@activity.defn
async def persistent_value_error_activity() -> None:
    raise ValueError("Activity failed!")


@workflow.defn
class RetryingActivityWorkflow:
    @workflow.run
    async def run(self, activity_name: str) -> None:
        await workflow.execute_activity(
            activity_name,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(milliseconds=1),
                maximum_interval=dt.timedelta(milliseconds=1),
                maximum_attempts=2,
            ),
        )


@pytest.mark.parametrize(
    "activity_name,expect_failure,expected_capture_count,expected_exc_type",
    [
        # A transient DB drop that recovers on retry must never reach error tracking.
        ("recovering_db_error_activity", False, 0, None),
        # A DB drop that never recovers is reported once, on the final attempt only.
        ("persistent_db_error_activity", True, 1, django.db.OperationalError),
        # Non-DB errors keep being reported on every attempt, retries remaining or not.
        ("persistent_value_error_activity", True, 2, ValueError),
    ],
)
@pytest.mark.asyncio
async def test_retryable_transient_db_error_is_not_reported_while_retries_remain(
    activity_name: str,
    expect_failure: bool,
    expected_capture_count: int,
    expected_exc_type: type[Exception] | None,
    temporal_client: Client,
):
    task_queue = "TEST-TASK-QUEUE"
    workflow_id = str(uuid.uuid4())

    with patch("posthog.temporal.common.posthog_client.capture_exception") as mock_ph_capture:
        async with Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[RetryingActivityWorkflow],
            activities=[
                recovering_db_error_activity,
                persistent_db_error_activity,
                persistent_value_error_activity,
            ],
            interceptors=[PostHogClientInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            run = temporal_client.execute_workflow(
                "RetryingActivityWorkflow",
                activity_name,
                id=workflow_id,
                task_queue=task_queue,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            if expect_failure:
                with pytest.raises(WorkflowFailureError):
                    await run
            else:
                await run

        assert mock_ph_capture.call_count == expected_capture_count
        if expected_exc_type is not None:
            captured_exc = mock_ph_capture.call_args_list[-1][0][0]
            assert isinstance(captured_exc, expected_exc_type)


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
