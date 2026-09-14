import uuid
import asyncio
import logging
import datetime as dt
from collections.abc import AsyncIterator, Iterator
from typing import Literal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import OperationalError

import pytest_asyncio
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.contrib.opentelemetry import OpenTelemetryPlugin
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    CancelledError,
    TerminatedError,
    TimeoutError,
    TimeoutType,
)
from temporalio.runtime import MetricBuffer, Runtime, TelemetryConfig
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.facade.temporal import (
    DELIVERY_ACTIVITIES,
    DELIVERY_WORKFLOWS,
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
    AlertsProductTelemetryInterceptor,
)
from products.alerts.backend.temporal import postgres
from products.alerts.backend.temporal.workflows import AlertsProductCheckDueWorkflow, AlertsProductInputs


@workflow.defn(name="test-alerts-product-close-after-child-start")
class CloseAfterChildStartWorkflow:
    @workflow.run
    async def run(self, close_mode: str) -> None:
        await AlertsProductCheckDueWorkflow().run(AlertsProductInputs())
        await workflow.execute_activity("test_confirm_child_start", start_to_close_timeout=dt.timedelta(seconds=5))
        if close_mode == "failed":
            raise ApplicationError("Test parent failure", non_retryable=True)
        await workflow.wait_condition(lambda: False)


@pytest.fixture(scope="module")
def sdk_metrics() -> MetricBuffer:
    return MetricBuffer(10000)


@pytest_asyncio.fixture(scope="module")
async def environment(
    sdk_metrics: MetricBuffer, span_exporter: InMemorySpanExporter
) -> AsyncIterator[WorkflowEnvironment]:
    runtime = Runtime(telemetry=TelemetryConfig(metrics=sdk_metrics))
    async with await WorkflowEnvironment.start_time_skipping(
        runtime=runtime, plugins=[OpenTelemetryPlugin(add_temporal_spans=True)]
    ) as env:
        yield env


@pytest.fixture(autouse=True)
def postgres_cursor() -> Iterator[MagicMock]:
    with patch.object(postgres, "execute_with_timeout") as execute:
        cursor = execute.return_value.__enter__.return_value
        cursor.fetchone.return_value = (1,)
        yield cursor


@pytest.mark.asyncio
@pytest.mark.parametrize("database_error", [False, True])
async def test_each_tick_starts_independent_delivery(
    environment: WorkflowEnvironment,
    caplog: pytest.LogCaptureFixture,
    sdk_metrics: MetricBuffer,
    span_exporter: InMemorySpanExporter,
    activity_logs,
    postgres_cursor: MagicMock,
    database_error: bool,
) -> None:
    if database_error:
        postgres_cursor.execute.side_effect = OperationalError("sensitive connection details")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    client = environment.client
    workflow_id = str(uuid.uuid4())
    child_ids: set[str] = set()
    span_exporter.clear()
    sdk_metrics.retrieve_updates()

    @activity.defn(name="alerts_product_deliver_activity")
    async def retry_delivery() -> None:
        if activity.info().attempt == 1:
            raise ApplicationError("sensitive retry exception")

    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
        workflows=EVALUATION_WORKFLOWS,
        activities=EVALUATION_ACTIVITIES,
        interceptors=[AlertsProductTelemetryInterceptor()],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        for _ in range(2):
            parent = await client.start_workflow(
                "alerts-product-check-due",
                AlertsProductInputs(),
                id=workflow_id,
                task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
                execution_timeout=dt.timedelta(seconds=10),
            )
            assert await parent.result() is None
            history = await parent.fetch_history()
            scheduled = [
                event.activity_task_scheduled_event_attributes
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
            ]
            assert len(scheduled) == 1
            assert scheduled[0].retry_policy.maximum_attempts == 1
            failure_count = sum(
                event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED for event in history.events
            )
            assert failure_count == int(database_error)
            assert "sensitive" not in str(history)
            children = [
                event.child_workflow_execution_started_event_attributes
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED
            ]
            assert len(children) == 1
            child_id = children[0].workflow_execution.workflow_id
            assert parent.first_execution_run_id is not None
            assert parent.first_execution_run_id in child_id
            assert children[0].workflow_type.name == "alerts-product-deliver"
            child_ids.add(child_id)
            child_description = await client.get_workflow_handle(child_id).describe()
            assert child_description.task_queue == settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE
            assert child_description.status == WorkflowExecutionStatus.RUNNING

    assert len(child_ids) == 2
    assert postgres_cursor.execute.call_count == 2
    assert "sensitive" not in caplog.text
    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
        workflows=DELIVERY_WORKFLOWS,
        activities=[retry_delivery],
        interceptors=[AlertsProductTelemetryInterceptor()],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        for child_id in child_ids:
            child = client.get_workflow_handle(child_id)
            assert await child.result() is None
            history = await child.fetch_history()
            scheduled = [
                event.activity_task_scheduled_event_attributes
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
            ]
            assert len(scheduled) == 1
            assert scheduled[0].retry_policy.maximum_attempts == 3

    updates = sdk_metrics.retrieve_updates()
    for metric_name in ("temporal_activity_schedule_to_start_latency", "temporal_activity_execution_latency"):
        for task_queue, expected_attempts in (
            (settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE, 2),
            (settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE, 4),
        ):
            samples = [
                update
                for update in updates
                if update.metric.name == metric_name and update.attributes.get("task_queue") == task_queue
            ]
            assert len(samples) == expected_attempts
            assert all(sample.value >= 0 for sample in samples)

    spans = span_exporter.get_finished_spans()
    spans_by_id = {span.context.span_id: span for span in spans}
    assert len(spans_by_id) == len(spans)
    workflow_spans = [span for span in spans if span.name.startswith("RunWorkflow:")]
    activity_spans = [span for span in spans if span.name.startswith("RunActivity:")]
    assert len(workflow_spans) == 4
    assert len(activity_spans) == 6
    for delivery in (span for span in workflow_spans if span.name == "RunWorkflow:alerts-product-deliver"):
        assert delivery.parent is not None
        child_start = spans_by_id[delivery.parent.span_id]
        assert child_start.parent is not None
        evaluation = spans_by_id[child_start.parent.span_id]
        assert child_start.name == "StartChildWorkflow:alerts-product-deliver"
        assert evaluation.name == "RunWorkflow:alerts-product-check-due"
        assert delivery.context.trace_id == child_start.context.trace_id == evaluation.context.trace_id
        assert evaluation.end_time is not None and delivery.start_time is not None
        assert evaluation.end_time <= delivery.start_time
    for attempt_span in activity_spans:
        assert attempt_span.parent is not None
        activity_start = spans_by_id[attempt_span.parent.span_id]
        assert activity_start.parent is not None
        workflow_span = spans_by_id[activity_start.parent.span_id]
        assert activity_start.name == attempt_span.name.replace("RunActivity:", "StartActivity:")
        assert workflow_span in workflow_spans
        assert attempt_span.context.trace_id == activity_start.context.trace_id == workflow_span.context.trace_id
        assert attempt_span.attributes is not None and workflow_span.attributes is not None
        assert attempt_span.attributes["temporalRunID"] == workflow_span.attributes["temporalRunID"]
        entries = [
            entry
            for entry in activity_logs
            if entry.get("span_id") == trace.format_span_id(attempt_span.context.span_id)
        ]
        assert [entry["event"] for entry in entries] == [
            "alerts_product_activity_started",
            "alerts_product_activity_finished",
        ]
        assert all(entry["trace_id"] == trace.format_trace_id(attempt_span.context.trace_id) for entry in entries)
        assert entries[0]["attempt"] == entries[1]["attempt"]
        assert entries[1]["outcome"] == (
            "failure"
            if (
                (attempt_span.name == "RunActivity:alerts_product_deliver_activity" and entries[1]["attempt"] == 1)
                or (attempt_span.name == "RunActivity:alerts_product_check_due_activity" and database_error)
            )
            else "success"
        )
    assert "sensitive" not in str(activity_logs)


@pytest.mark.asyncio
@pytest.mark.parametrize("close_mode", ["failed", "terminated"])
async def test_delivery_survives_parent_closure(
    environment: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, close_mode: Literal["failed", "terminated"]
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    client = environment.client
    child_started = asyncio.Event()

    @activity.defn(name="test_confirm_child_start")
    async def confirm_child_start() -> None:
        child_started.set()

    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
        workflows=[CloseAfterChildStartWorkflow],
        activities=[*EVALUATION_ACTIVITIES, confirm_child_start],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        parent = await client.start_workflow(
            CloseAfterChildStartWorkflow.run,
            close_mode,
            id=str(uuid.uuid4()),
            task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
            execution_timeout=dt.timedelta(seconds=10),
        )
        await asyncio.wait_for(child_started.wait(), timeout=10)
        child_id = f"alerts-product-deliver-{parent.first_execution_run_id}"

        if close_mode == "terminated":
            await parent.terminate()
        with pytest.raises(WorkflowFailureError) as failure:
            await parent.result()
        assert isinstance(failure.value.cause, ApplicationError if close_mode == "failed" else TerminatedError)

    child = client.get_workflow_handle(child_id)
    assert (await child.describe()).status == WorkflowExecutionStatus.RUNNING
    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
        workflows=DELIVERY_WORKFLOWS,
        activities=DELIVERY_ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        assert await child.result() is None


@pytest.mark.parametrize("timeout_type", [TimeoutType.START_TO_CLOSE, TimeoutType.SCHEDULE_TO_CLOSE])
async def test_probe_timeout_still_starts_independent_delivery(
    environment: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, timeout_type: TimeoutType
) -> None:
    caplog.set_level(logging.WARNING, logger="temporalio.workflow")
    activity_started = asyncio.Event()
    release_activity = asyncio.Event()

    @activity.defn(name="alerts_product_check_due_activity")
    async def blocked_probe() -> None:
        activity_started.set()
        await release_activity.wait()

    client = environment.client
    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
        workflows=EVALUATION_WORKFLOWS,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        parent = await client.start_workflow(
            AlertsProductCheckDueWorkflow.run,
            AlertsProductInputs(),
            id=str(uuid.uuid4()),
            task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
            execution_timeout=dt.timedelta(seconds=50),
        )
        async with asyncio.timeout(10):
            while not any(
                event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
                for event in (await parent.fetch_history()).events
            ):
                pass
        if timeout_type == TimeoutType.SCHEDULE_TO_CLOSE:
            # Separate the close deadlines instead of racing schedule-to-start at the same deadline.
            await environment.sleep(25)
        async with Worker(
            client,
            task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
            activities=[blocked_probe],
        ):
            try:
                await asyncio.wait_for(activity_started.wait(), timeout=5)
                await parent.result()
            finally:
                release_activity.set()
        history = await parent.fetch_history()
        timeouts = [
            event.activity_task_timed_out_event_attributes
            for event in history.events
            if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT
        ]
        assert len(timeouts) == 1
        assert timeouts[0].failure.timeout_failure_info.timeout_type == int(timeout_type)
        child = client.get_workflow_handle(f"alerts-product-deliver-{parent.first_execution_run_id}")
        assert (await child.describe()).status == WorkflowExecutionStatus.RUNNING

    observation = "Postgres probe timed out; database outcome unknown; delivery is continuing"
    assert caplog.text.count(observation) == 1
    await Replayer(workflows=EVALUATION_WORKFLOWS, workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(history)
    assert caplog.text.count(observation) == 1
    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
        workflows=DELIVERY_WORKFLOWS,
        activities=DELIVERY_ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        assert await child.result() is None


@pytest.mark.parametrize(
    "cause",
    [
        ApplicationError("Unrelated failure", type="OtherFailure"),
        CancelledError(),
        TimeoutError("Heartbeat timeout", type=TimeoutType.HEARTBEAT, last_heartbeat_details=[]),
        TimeoutError("Schedule-to-start timeout", type=TimeoutType.SCHEDULE_TO_START, last_heartbeat_details=[]),
    ],
)
async def test_probe_unrelated_activity_failures_do_not_start_delivery(cause: Exception) -> None:
    error = ActivityError(
        "Activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="test-worker",
        activity_type="alerts_product_check_due_activity",
        activity_id="1",
        retry_state=None,
    )
    error.__cause__ = cause
    with (
        patch.object(workflow, "execute_activity", AsyncMock(side_effect=error)),
        patch.object(workflow, "start_child_workflow", AsyncMock()) as start_delivery,
        pytest.raises(ActivityError) as caught,
    ):
        await AlertsProductCheckDueWorkflow().run(AlertsProductInputs())
    assert caught.value is error
    start_delivery.assert_not_awaited()


async def test_probe_workflow_cancellation_does_not_start_delivery() -> None:
    with (
        patch.object(workflow, "execute_activity", AsyncMock(side_effect=asyncio.CancelledError)),
        patch.object(workflow, "start_child_workflow", AsyncMock()) as start_delivery,
        pytest.raises(asyncio.CancelledError),
    ):
        await AlertsProductCheckDueWorkflow().run(AlertsProductInputs())
    start_delivery.assert_not_awaited()
