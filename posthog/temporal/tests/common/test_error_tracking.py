"""Test that we capture exceptions in activities and workflows to PostHog."""

import uuid
import socket
import datetime as dt
from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import patch

from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.temporal.common.posthog_client import PostHogClientInterceptor, _is_transient_dns_error


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


@activity.defn
async def egress_backpressure_activity(inputs: OptionallyFailingInputs) -> None:
    raise GitHubEgressBudgetExhausted("GitHub egress budget exhausted for installation 123; deferring")


@workflow.defn
class EgressBackpressureActivityWorkflow:
    @workflow.run
    async def run(self, inputs: OptionallyFailingInputs) -> None:
        await workflow.execute_activity(
            egress_backpressure_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            heartbeat_timeout=dt.timedelta(seconds=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@activity.defn
async def dns_failure_activity(inputs: OptionallyFailingInputs) -> None:
    # aiohttp's ClientConnectorDNSError chains a socket.gaierror via `from`; libpq (Postgres)
    # instead surfaces name-resolution failures as message text on an OperationalError. Raise the
    # underlying gaierror to stand in for the connection-time DNS blip both wrap.
    raise socket.gaierror(-2, "Name or service not known")


@workflow.defn
class DnsFailureActivityWorkflow:
    @workflow.run
    async def run(self, inputs: OptionallyFailingInputs) -> None:
        await workflow.execute_activity(
            dns_failure_activity,
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


@pytest.mark.asyncio
async def test_egress_backpressure_is_not_captured(temporal_client: Client):
    """An egress-budget backpressure error (our own limiter shedding a deferrable call so Temporal
    retries later) is expected control flow, not a defect, so the interceptor must re-raise it
    without reporting it to error tracking."""
    task_queue = "TEST-TASK-QUEUE"
    workflow_id = str(uuid.uuid4())

    with patch("posthog.temporal.common.posthog_client.capture_exception") as mock_ph_capture:
        async with Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[EgressBackpressureActivityWorkflow],
            activities=[egress_backpressure_activity],
            interceptors=[PostHogClientInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await temporal_client.execute_workflow(
                    "EgressBackpressureActivityWorkflow",
                    OptionallyFailingInputs(fail=True),
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        mock_ph_capture.assert_not_called()


class TestIsTransientDnsError:
    @parameterized.expand(
        [
            ("direct_gaierror", socket.gaierror(-2, "Name or service not known"), True),
            (
                "aiohttp_style_chained_gaierror",
                ConnectionError("Cannot connect to host clickhouse"),
                True,
            ),
            (
                "libpq_message_errno_2",
                Exception(
                    'connection failed: could not translate host name "pg" to address: Name or service not known'
                ),
                True,
            ),
            (
                "libpq_message_temporary_failure",
                Exception("could not translate host name: Temporary failure in name resolution"),
                True,
            ),
            ("unrelated_value_error", ValueError("Activity failed!"), False),
            ("unrelated_connection_reset", ConnectionResetError("Connection reset by peer"), False),
        ]
    )
    def test_detection(self, _name: str, exc: BaseException, expected: bool):
        if _name == "aiohttp_style_chained_gaierror":
            # Rebuild the aiohttp shape: a ClientConnector-style error whose __cause__ is the gaierror.
            exc.__cause__ = socket.gaierror(-3, "Temporary failure in name resolution")
        assert _is_transient_dns_error(exc) is expected


@pytest.mark.asyncio
async def test_dns_failure_is_not_captured(temporal_client: Client):
    """A transient DNS / name-resolution failure (an infra blip Temporal's retry policy recovers
    from) is expected control flow, not a defect, so the interceptor must re-raise it without
    reporting it to error tracking. Guards that _is_transient_dns_error is actually wired into the
    activity interceptor's skip condition."""
    task_queue = "TEST-TASK-QUEUE"
    workflow_id = str(uuid.uuid4())

    with patch("posthog.temporal.common.posthog_client.capture_exception") as mock_ph_capture:
        async with Worker(
            temporal_client,
            task_queue=task_queue,
            workflows=[DnsFailureActivityWorkflow],
            activities=[dns_failure_activity],
            interceptors=[PostHogClientInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await temporal_client.execute_workflow(
                    "DnsFailureActivityWorkflow",
                    OptionallyFailingInputs(fail=True),
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        mock_ph_capture.assert_not_called()


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
