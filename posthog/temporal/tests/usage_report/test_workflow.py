"""End-to-end workflow tests using a Temporal `WorkflowEnvironment`.

The activities are mocked at the `@activity.defn` boundary so the workflow's
orchestration logic — query fan-out, aggregation, and SQS pointer dispatch —
can be verified without standing up real ClickHouse / Postgres / S3.
"""

import uuid
from datetime import UTC, datetime

import pytest

import temporalio.worker
from parameterized import parameterized
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
from posthog.temporal.usage_report.workflow import RunUsageReportsWorkflow, build_context


@parameterized.expand(
    [
        # (day_offset, now, expected_date, expected_completeness) — intraday run mid-day reports today
        (0, datetime(2026, 5, 4, 13, 45, tzinfo=UTC), "2026-05-04", "partial"),
        # intraday run just after midnight still reports the new day, not yesterday
        (0, datetime(2026, 5, 4, 1, 45, tzinfo=UTC), "2026-05-04", "partial"),
        # finalizer run early morning reports the completed previous day
        (1, datetime(2026, 5, 4, 3, 0, tzinfo=UTC), "2026-05-03", "complete"),
        # manual backfill of an older day is also complete
        (3, datetime(2026, 5, 4, 3, 0, tzinfo=UTC), "2026-05-01", "complete"),
    ]
)
def test_build_context_reports_full_day_at_offset(
    day_offset: int, now: datetime, expected_date: str, expected_completeness: str
) -> None:
    ctx = build_context(RunUsageReportsInputs(day_offset=day_offset), run_id="run-1", now=now)

    assert ctx.date_str == expected_date
    assert ctx.report_completeness == expected_completeness
    assert ctx.period_start.isoformat() == f"{expected_date}T00:00:00+00:00"
    assert ctx.period_end.isoformat() == f"{expected_date}T23:59:59.999999+00:00"


@pytest.mark.asyncio
async def test_workflow_runs_query_then_aggregate() -> None:
    seen_query_names: list[str] = []
    aggregated_with: list[list[str]] = []
    aggregate_payloads: list[AggregateInputs] = []
    pointer_payloads: list[EnqueuePointerInputs] = []
    expected_aggregate = AggregateResult(
        chunk_keys=["chunks/chunk_0000.jsonl.gz"],
        manifest_key="manifest.json",
        total_orgs=2,
        total_orgs_with_usage=1,
    )

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
        aggregate_payloads.append(inputs)
        aggregated_with.append([r.query_name for r in inputs.query_results])
        return expected_aggregate

    @activity.defn(name="usage-reports-enqueue-pointer-message")
    async def pointer_mock(inputs: EnqueuePointerInputs) -> None:
        pointer_payloads.append(inputs)

    task_queue = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
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
                RunUsageReportsInputs(day_offset=1),
                id=workflow_id,
                task_queue=task_queue,
            )

        # Verify the per-query activity scheduling carried `summary=spec.name`
        # so the Temporal UI shows which query is running.
        handle = env.client.get_workflow_handle(workflow_id)
        scheduled_summaries: dict[str, str] = {}
        async for event in handle.fetch_history_events():
            attrs = event.activity_task_scheduled_event_attributes
            if attrs.activity_type.name != "run-usage-report-query":
                continue
            assert event.user_metadata.HasField("summary"), f"activity {attrs.activity_id} scheduled without a summary"
            (decoded_summary,) = pydantic_data_converter.payload_converter.from_payloads(
                [event.user_metadata.summary], [str]
            )
            scheduled_summaries[attrs.activity_id] = decoded_summary

    expected_names = [spec.name for spec in QUERIES]
    # Queries run with bounded concurrency, so completion order is not
    # deterministic — only assert the set. Result ordering (passed to the
    # aggregator) is preserved via `asyncio.gather`.
    assert set(seen_query_names) == set(expected_names)
    assert len(seen_query_names) == len(expected_names)

    assert len(aggregated_with) == 1
    assert aggregated_with[0] == expected_names

    assert len(pointer_payloads) == 1
    assert pointer_payloads[0].ctx == aggregate_payloads[0].ctx
    assert pointer_payloads[0].aggregate == expected_aggregate

    # Each scheduled query activity carries its query name as the Temporal
    # `summary`, so the UI surfaces which query is running.
    assert set(scheduled_summaries.values()) == set(expected_names)
    assert len(scheduled_summaries) == len(expected_names)

    assert result == expected_aggregate.model_dump()
