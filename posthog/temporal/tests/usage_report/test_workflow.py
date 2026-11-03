"""End-to-end workflow tests using a Temporal `WorkflowEnvironment`.

The activities are mocked at the `@activity.defn` boundary so the workflow's
orchestration logic — query fan-out, aggregation, and SQS pointer dispatch —
can be verified without standing up real ClickHouse / Postgres / S3.
"""

import uuid
import asyncio
import logging
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from django.test import override_settings

import temporalio.worker
from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from posthog.temporal.quota_limiting.run_quota_limiting import (
    QuotaLimitingResult,
    RunQuotaLimitingAllOrgsInputs,
    RunQuotaLimitingInputs,
    RunQuotaLimitingWorkflow,
)
from posthog.temporal.usage_report.activities import plan_usage_counters
from posthog.temporal.usage_report.queries import QUERIES, QuerySpec
from posthog.temporal.usage_report.types import (
    AggregateInputs,
    AggregateResult,
    EnqueuePointerInputs,
    RunLegacyCounterInputs,
    RunQueryToS3Inputs,
    RunQueryToS3Result,
    RunUsageReportsInputs,
    WorkflowContext,
)
from posthog.temporal.usage_report.workflow import (
    AGGREGATION_QUEUE_PATCH_ID,
    LOGS_DISTINCT_PATTERNS_QUERY_NAME,
    MCP_EVENT_COUNT_QUERY_NAME,
    PARALLEL_COUNTER_QUERIES_PATCH_ID,
    QUERY_CONCURRENCY,
    REPLAY_VISION_SPEND_PROJECTION_QUERY_NAME,
    SANDBOX_COMPUTE_QUERY_NAME,
    TRANSACTIONAL_EMAILS_QUERY_NAME,
    USAGE_COUNTER_SERVICE_PATCH_ID,
    RunUsageReportsWorkflow,
    _queries_for_logs_distinct_patterns_patch,
    _queries_for_mcp_event_count_patch,
    _queries_for_replay_vision_spend_projection_patch,
    _queries_for_sandbox_compute_patch,
    _queries_for_transactional_emails_patch,
    build_context,
)
from posthog.usage_counters import (
    COUNTER_FLAG_NAMES,
    LEGACY_QUERY_NAMES,
    UsageCounter,
    UsageCounterMode,
    UsageCounterPlan,
)


def test_sandbox_compute_query_is_versioned_for_existing_histories() -> None:
    assert SANDBOX_COMPUTE_QUERY_NAME not in [spec.name for spec in _queries_for_sandbox_compute_patch(False)]
    assert SANDBOX_COMPUTE_QUERY_NAME in [spec.name for spec in _queries_for_sandbox_compute_patch(True)]


@parameterized.expand(
    [
        ("logs_distinct_patterns", _queries_for_logs_distinct_patterns_patch, LOGS_DISTINCT_PATTERNS_QUERY_NAME),
        ("transactional_emails", _queries_for_transactional_emails_patch, TRANSACTIONAL_EMAILS_QUERY_NAME),
        ("mcp_event_count", _queries_for_mcp_event_count_patch, MCP_EVENT_COUNT_QUERY_NAME),
        (
            "replay_vision_spend_projection",
            _queries_for_replay_vision_spend_projection_patch,
            REPLAY_VISION_SPEND_PROJECTION_QUERY_NAME,
        ),
    ]
)
def test_single_query_is_versioned_for_existing_histories(
    _name: str, queries_for_patch: Callable[[list[QuerySpec], bool], list[QuerySpec]], query_name: str
) -> None:
    assert query_name not in [spec.name for spec in queries_for_patch(QUERIES, False)]
    assert query_name in [spec.name for spec in queries_for_patch(QUERIES, True)]


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
@pytest.mark.parametrize(
    "inputs, invalid_field",
    [
        # A negative offset reports a future empty day and marks it "complete" for billing.
        (RunUsageReportsInputs(day_offset=-1), "day_offset"),
        # A malformed id fails aggregation only after every gather query has run.
        (RunUsageReportsInputs(organization_ids=["not-a-uuid"]), "organization_ids"),
    ],
)
async def test_workflow_rejects_invalid_inputs_before_running_queries(
    inputs: RunUsageReportsInputs, invalid_field: str
) -> None:
    ran_queries: list[str] = []

    @activity.defn(name="run-usage-report-query")
    async def query_mock(inputs: RunQueryToS3Inputs) -> RunQueryToS3Result:
        ran_queries.append(inputs.query_name)
        return RunQueryToS3Result(query_name=inputs.query_name, s3_key="unused", duration_ms=1)

    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=str(uuid.uuid4()),
            workflows=[RunUsageReportsWorkflow],
            activities=[query_mock],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ) as worker:
            with pytest.raises(WorkflowFailureError) as exc_info:
                await env.client.execute_workflow(
                    RunUsageReportsWorkflow.run,
                    inputs,
                    id=str(uuid.uuid4()),
                    task_queue=worker.task_queue,
                )

    cause = exc_info.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.non_retryable
    assert invalid_field in str(cause)
    assert ran_queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "report_behavior",
    [
        "disabled",
        "enabled",
        "activity_failure",
        "query_failure",
        "flag_failure",
        "partial",
        "pre_patch",
        "pre_patch_query_failure",
        "concurrency",
        "serial_counters",
        "counter_query_failure",
        "pre_aggregation_queue",
        "aggregation_queue",
    ],
)
async def test_workflow_runs_query_then_aggregate(report_behavior: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    seen_query_names: list[str] = []
    seen_counters: list[UsageCounter] = []
    aggregated_with: list[list[str]] = []
    aggregate_payloads: list[AggregateInputs] = []
    pointer_payloads: list[EnqueuePointerInputs] = []
    plans: list[UsageCounterPlan] = []
    counter_contexts: list[WorkflowContext] = []
    query_started = asyncio.Event()
    counter_started = asyncio.Event()
    release_queries = asyncio.Event()
    aggregation_started = asyncio.Event()
    release_aggregation = asyncio.Event()
    active_aggregations = 0
    max_active_aggregations = 0
    starts: asyncio.Queue[str] = asyncio.Queue()
    releases: dict[str, asyncio.Event] = {}
    active_queries: set[str] = set()
    active_counters: set[str] = set()
    max_active = 0
    max_active_counters = 0
    fails = report_behavior in {"activity_failure", "query_failure", "pre_patch_query_failure", "counter_query_failure"}
    pre_patch = report_behavior.startswith("pre_patch")
    legacy_aggregation_queue = pre_patch or report_behavior == "pre_aggregation_queue"
    parallel_counters = not pre_patch and report_behavior != "serial_counters"
    expected_counter_report = RunQueryToS3Result(
        query_name="usage_counters", s3_key="queries/counters.json", duration_ms=1
    )
    expected_aggregate = AggregateResult(
        chunk_keys=["chunks/chunk_0000.jsonl.gz"],
        manifest_key="manifest.json",
        total_orgs=2,
        total_orgs_with_usage=1,
    )

    @activity.defn(name="plan-usage-counters")
    async def plan_mock(ctx: WorkflowContext) -> UsageCounterPlan:
        with patch(
            "posthoganalytics.get_feature_flag", return_value="legacy" if report_behavior == "disabled" else "both"
        ) as flag:
            if report_behavior == "flag_failure":
                flag.side_effect = RuntimeError("flag service unavailable")
            plan = await plan_usage_counters(ctx)
        plans.append(plan)
        return plan

    @activity.defn(name="fetch-usage-counter-report")
    async def fetch_mock(ctx: WorkflowContext) -> RunQueryToS3Result:
        counter_contexts.append(ctx)
        counter_started.set()
        if report_behavior == "activity_failure":
            await query_started.wait()
            raise ApplicationError("unavailable", non_retryable=True)
        if report_behavior == "query_failure":
            await release_queries.wait()
        return expected_counter_report

    async def wait_for_query_release(name: str, *, counter: bool = False) -> None:
        nonlocal max_active, max_active_counters
        if report_behavior != "concurrency":
            return
        active_queries.add(name)
        if counter:
            active_counters.add(name)
        max_active = max(max_active, len(active_queries))
        max_active_counters = max(max_active_counters, len(active_counters))
        releases[name] = asyncio.Event()
        starts.put_nowait(name)
        try:
            await releases[name].wait()
        finally:
            active_queries.remove(name)
            active_counters.discard(name)

    @activity.defn(name="run-legacy-usage-counter")
    async def legacy_counter_mock(inputs: RunLegacyCounterInputs) -> bool:
        seen_counters.append(inputs.counter)
        if report_behavior == "counter_query_failure":
            raise ApplicationError("counter query unavailable", non_retryable=True)
        await wait_for_query_release(LEGACY_QUERY_NAMES.get(inputs.counter, inputs.counter.value), counter=True)
        return True

    @activity.defn(name="run-usage-report-query")
    async def query_mock(inputs: RunQueryToS3Inputs) -> RunQueryToS3Result:
        seen_query_names.append(inputs.query_name)
        query_started.set()
        await wait_for_query_release(inputs.query_name)
        if report_behavior in {"activity_failure", "counter_query_failure"} and len(seen_query_names) == 1:
            await release_queries.wait()
        if report_behavior in {"query_failure", "pre_patch_query_failure"}:
            raise ApplicationError("query unavailable", non_retryable=True)
        return RunQueryToS3Result(
            query_name=inputs.query_name,
            s3_key=f"queries/{inputs.query_name}.json",
            duration_ms=1,
        )

    @activity.defn(name="aggregate-and-chunk-org-reports")
    async def aggregate_mock(inputs: AggregateInputs) -> AggregateResult:
        nonlocal active_aggregations, max_active_aggregations
        aggregate_payloads.append(inputs)
        aggregated_with.append([r.query_name for r in inputs.query_results])
        active_aggregations += 1
        max_active_aggregations = max(max_active_aggregations, active_aggregations)
        aggregation_started.set()
        try:
            if report_behavior == "aggregation_queue":
                await release_aggregation.wait()
            return expected_aggregate
        finally:
            active_aggregations -= 1

    @activity.defn(name="run-quota-limiting-all-orgs")
    async def quota_mock(inputs: RunQuotaLimitingAllOrgsInputs) -> QuotaLimitingResult:
        return QuotaLimitingResult(orgs_processed=1)

    @activity.defn(name="usage-reports-enqueue-pointer-message")
    async def pointer_mock(inputs: EnqueuePointerInputs) -> None:
        pointer_payloads.append(inputs)

    task_queue = str(uuid.uuid4())
    aggregation_queue = f"{task_queue}-aggregation"
    workflow_id = str(uuid.uuid4())
    with override_settings(USAGE_REPORT_AGGREGATION_TASK_QUEUE=aggregation_queue):
        async with (
            await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env,
            Worker(
                env.client,
                task_queue=aggregation_queue,
                activities=[aggregate_mock],
                max_concurrent_activities=1,
            ),
            Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunUsageReportsWorkflow, RunQuotaLimitingWorkflow],
                activities=[
                    query_mock,
                    aggregate_mock,
                    pointer_mock,
                    plan_mock,
                    fetch_mock,
                    legacy_counter_mock,
                    quota_mock,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ),
        ):
            patched = workflow.patched
            with (
                patch(
                    "temporalio.workflow.patched",
                    side_effect=lambda name: (
                        False
                        if (pre_patch and name == USAGE_COUNTER_SERVICE_PATCH_ID)
                        or (report_behavior == "serial_counters" and name == PARALLEL_COUNTER_QUERIES_PATCH_ID)
                        or (legacy_aggregation_queue and name == AGGREGATION_QUEUE_PATCH_ID)
                        else patched(name)
                    ),
                )
                if legacy_aggregation_queue or report_behavior == "serial_counters"
                else nullcontext()
            ):
                try:
                    with pytest.raises(WorkflowFailureError) if fails else nullcontext():
                        run = asyncio.create_task(
                            env.client.execute_workflow(
                                RunUsageReportsWorkflow.run,
                                RunUsageReportsInputs(day_offset=0 if report_behavior == "partial" else 1),
                                id=workflow_id,
                                task_queue=task_queue,
                                execution_timeout=timedelta(minutes=2),
                            ),
                        )
                        if report_behavior == "concurrency":
                            for offset in range(0, len(QUERIES), QUERY_CONCURRENCY):
                                batch = [
                                    await asyncio.wait_for(starts.get(), timeout=10)
                                    for _ in range(min(QUERY_CONCURRENCY, len(QUERIES) - offset))
                                ]
                                for name in batch:
                                    releases[name].set()
                        if report_behavior == "aggregation_queue":
                            await asyncio.wait_for(aggregation_started.wait(), timeout=10)
                            second = await env.client.start_workflow(
                                RunUsageReportsWorkflow.run,
                                RunUsageReportsInputs(day_offset=0),
                                id=str(uuid.uuid4()),
                                task_queue=task_queue,
                                execution_timeout=timedelta(minutes=2),
                            )
                            async with asyncio.timeout(30):
                                async for event in second.fetch_history_events(wait_new_event=True):
                                    if (
                                        event.activity_task_scheduled_event_attributes.activity_type.name
                                        == "aggregate-and-chunk-org-reports"
                                    ):
                                        break
                                quota = await env.client.execute_workflow(
                                    RunQuotaLimitingWorkflow.run,
                                    RunQuotaLimitingInputs(),
                                    id=str(uuid.uuid4()),
                                    task_queue=task_queue,
                                    execution_timeout=timedelta(minutes=2),
                                )
                                assert quota.orgs_processed == 1
                                pending = (await second.describe()).raw_description.pending_activities
                                assert len(pending) == 1
                                assert pending[0].state == PendingActivityState.PENDING_ACTIVITY_STATE_SCHEDULED
                                assert len(aggregate_payloads) == 1
                                release_aggregation.set()
                                assert await second.result() == expected_aggregate.model_dump()
                            assert max_active_aggregations == 1
                        result = await asyncio.wait_for(run, timeout=30 if fails else 120)
                finally:
                    release_queries.set()
                    release_aggregation.set()
                    for release in releases.values():
                        release.set()

            # Each query activity carries a readable summary in the Temporal UI.
            handle = env.client.get_workflow_handle(workflow_id)
            history = await handle.fetch_history()
            scheduled_summaries: dict[str, str] = {}
            async for event in handle.fetch_history_events():
                attrs = event.activity_task_scheduled_event_attributes
                if attrs.activity_type.name == "aggregate-and-chunk-org-reports":
                    assert attrs.task_queue.name == (task_queue if legacy_aggregation_queue else aggregation_queue)
                if attrs.activity_type.name not in {"run-usage-report-query", "run-legacy-usage-counter"}:
                    continue
                assert event.user_metadata.HasField("summary"), (
                    f"activity {attrs.activity_id} scheduled without a summary"
                )
                (decoded_summary,) = pydantic_data_converter.payload_converter.from_payloads(
                    [event.user_metadata.summary], [str]
                )
                scheduled_summaries[attrs.activity_id] = decoded_summary

    counter_names = plans[0].query_names if plans else set()
    expected_names = [spec.name for spec in QUERIES if spec.name not in counter_names]
    with override_settings(USAGE_REPORT_AGGREGATION_TASK_QUEUE=aggregation_queue):
        await Replayer(
            workflows=[RunUsageReportsWorkflow],
            data_converter=pydantic_data_converter,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ).replay_workflow(history)
    if fails:
        assert set(seen_query_names) <= set(expected_names)
        assert aggregated_with == []
        assert pointer_payloads == []
        return
    if report_behavior == "aggregation_queue":
        assert len(aggregate_payloads) == len(pointer_payloads) == 2
        return

    # Queries run with bounded concurrency, so completion order is not
    # deterministic — only assert the set. Result ordering (passed to the
    # aggregator) is preserved via `asyncio.gather`.
    assert set(seen_query_names) == set(expected_names)
    assert len(seen_query_names) == len(expected_names)
    expected_counters = plans[0].legacy_counters if parallel_counters else []
    assert set(seen_counters) == set(expected_counters)
    assert len(seen_counters) == len(expected_counters)
    if report_behavior == "concurrency":
        assert max_active == QUERY_CONCURRENCY
        assert max_active_counters == QUERY_CONCURRENCY

    assert len(aggregated_with) == 1
    assert aggregated_with[0] == expected_names

    assert len(pointer_payloads) == 1
    assert pointer_payloads[0].ctx == aggregate_payloads[0].ctx
    assert pointer_payloads[0].aggregate == expected_aggregate
    assert len(plans) == (0 if report_behavior == "pre_patch" else 1)
    assert len(counter_contexts) == (0 if report_behavior == "pre_patch" else 1)
    assert aggregate_payloads[0].counter_result == (expected_counter_report if report_behavior != "pre_patch" else None)
    if counter_contexts:
        assert counter_contexts[0].usage_counter_plan == plans[0]
        assert counter_contexts[0].prepared_legacy_counters == (plans[0].legacy_counters if parallel_counters else None)
        expected_mode = (
            UsageCounterMode.LEGACY if report_behavior in {"disabled", "flag_failure"} else UsageCounterMode.BOTH
        )
        assert plans[0].modes == {
            counter: expected_mode if counter in COUNTER_FLAG_NAMES else UsageCounterMode.LEGACY
            for counter in UsageCounter
        }
    assert aggregate_payloads[0].ctx.usage_counter_plan == (plans[0] if plans else None)

    # Each scheduled query activity carries its query name as the Temporal
    # `summary`, so the UI surfaces which query is running.
    expected_summaries = set(expected_names) | {
        LEGACY_QUERY_NAMES.get(counter, counter.value) for counter in expected_counters
    }
    assert set(scheduled_summaries.values()) == expected_summaries
    assert len(scheduled_summaries) == len(expected_summaries)

    assert result == expected_aggregate.model_dump()
