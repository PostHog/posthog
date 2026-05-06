"""End-to-end workflow tests using a Temporal `WorkflowEnvironment`.

The activities are mocked at the `@activity.defn` boundary so the workflow's
orchestration logic — query fan-out, aggregation, SQS pointer — can be
verified without standing up real ClickHouse / Postgres / S3.
"""

import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.usage_report.queries import QUERIES
from posthog.temporal.usage_report.types import (
    AggregateInputs,
    AggregateResult,
    EnqueuePointerInputs,
    RunQueryToS3Inputs,
    RunQueryToS3Result,
    RunUsageReportsInputs,
)
from posthog.temporal.usage_report.workflow import RunUsageReportsWorkflow


@pytest.mark.asyncio
async def test_workflow_runs_query_aggregate_pointer_in_order() -> None:
    seen_query_names: list[str] = []
    aggregated_with: list[list[str]] = []
    pointer_payloads: list[EnqueuePointerInputs] = []

    @activity.defn(name="run-usage-report-query")
    async def query_mock(inputs: RunQueryToS3Inputs) -> RunQueryToS3Result:
        seen_query_names.append(inputs.query_name)
        return RunQueryToS3Result(
            query_name=inputs.query_name,
            s3_key=f"queries/{inputs.query_name}.json",
            duration_ms=1,
        )

    @activity.defn(name="aggregate-and-chunk-org-reports")
    async def aggregate_mock(inputs: AggregateInputs) -> AggregateResult:
        aggregated_with.append([r.query_name for r in inputs.query_results])
        return AggregateResult(
            chunk_keys=["chunks/chunk_0000.jsonl.gz"],
            manifest_key="manifest.json",
            total_orgs=2,
            total_orgs_with_usage=1,
        )

    @activity.defn(name="usage-reports-enqueue-pointer-message")
    async def pointer_mock(inputs: EnqueuePointerInputs) -> None:
        pointer_payloads.append(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RunUsageReportsWorkflow],
            activities=[query_mock, aggregate_mock, pointer_mock],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                RunUsageReportsWorkflow.run,
                RunUsageReportsInputs(at="2026-05-04T12:00:00+00:00"),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    expected_names = [spec.name for spec in QUERIES]
    assert seen_query_names == expected_names

    assert len(aggregated_with) == 1
    assert aggregated_with[0] == expected_names

    assert len(pointer_payloads) == 1
    pointer = pointer_payloads[0]
    assert pointer.aggregate.chunk_keys == ["chunks/chunk_0000.jsonl.gz"]
    assert pointer.aggregate.total_orgs == 2

    assert (
        result
        == AggregateResult(
            chunk_keys=["chunks/chunk_0000.jsonl.gz"],
            manifest_key="manifest.json",
            total_orgs=2,
            total_orgs_with_usage=1,
        ).model_dump()
    )
