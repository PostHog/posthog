import uuid
import asyncio
import logging
import datetime as dt
from collections.abc import AsyncIterator
from typing import Literal

import pytest

from django.conf import settings

import pytest_asyncio
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.contrib.opentelemetry import OpenTelemetryPlugin
from temporalio.exceptions import ApplicationError, TerminatedError
from temporalio.runtime import MetricBuffer, Runtime, TelemetryConfig
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.facade.temporal import (
    DELIVERY_ACTIVITIES,
    DELIVERY_WORKFLOWS,
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
    AlertsProductTelemetryInterceptor,
)
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


@pytest.mark.asyncio
async def test_each_tick_starts_independent_delivery(
    environment: WorkflowEnvironment,
    caplog: pytest.LogCaptureFixture,
    sdk_metrics: MetricBuffer,
    span_exporter: InMemorySpanExporter,
    activity_logs,
) -> None:
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
            child = await client.get_workflow_handle(child_id).describe()
            assert child.task_queue == settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE
            assert child.status == WorkflowExecutionStatus.RUNNING

    assert len(child_ids) == 2
    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
        workflows=DELIVERY_WORKFLOWS,
        activities=[retry_delivery],
        interceptors=[AlertsProductTelemetryInterceptor()],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        for child_id in child_ids:
            assert await client.get_workflow_handle(child_id).result() is None

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
            if attempt_span.name == "RunActivity:alerts_product_deliver_activity" and entries[1]["attempt"] == 1
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
