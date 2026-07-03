"""Temporal workflow that aggregates daily usage data and publishes it to S3
for the billing service.

The workflow runs ~50 gather queries (each as its own retriable activity),
then a single aggregation activity reads them all back from S3, builds one
`FullUsageReport` dict per organization, and writes those reports as gzipped
JSONL chunks (≤10k orgs each) plus a manifest.

The final step is an `enqueue_pointer_message` activity that sends a single
SQS pointer to billing so it can read the chunks and manifest from S3.

This replaces the per-org SQS fan-out in
`posthog/tasks/usage_report.py:send_all_org_usage_reports`. The Celery task
remains in production until billing migrates to consume the S3 layout.
"""

import json
import asyncio
from datetime import UTC, datetime, time, timedelta

from temporalio import common, workflow
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.usage_report.activities import (
    aggregate_and_chunk_org_reports,
    enqueue_pointer_message,
    run_query_to_s3,
)
from posthog.temporal.usage_report.metrics import get_workflow_finished_metric, record_workflow_latency
from posthog.temporal.usage_report.queries import QUERIES, QuerySpec
from posthog.temporal.usage_report.storage import run_prefix
from posthog.temporal.usage_report.types import (
    AggregateInputs,
    EnqueuePointerInputs,
    RunQueryToS3Inputs,
    RunQueryToS3Result,
    RunUsageReportsInputs,
    WorkflowContext,
)

# Cap concurrent gather queries so we don't overwhelm ClickHouse / Postgres
# with ~40 simultaneous heavy queries.
QUERY_CONCURRENCY = 4


def build_context(inputs: RunUsageReportsInputs, run_id: str, now: datetime) -> WorkflowContext:
    """Compute the period and S3 layout context. Pure function so it's safe
    to call from the workflow body (no real-time access).

    The period is always the full UTC day `inputs.day_offset` days before
    `now`. For `day_offset=0` (today) the tail of the window is in the
    future and simply matches no events, so intraday and finalizer runs
    share one code path.
    """
    report_day = (now.astimezone(UTC) - timedelta(days=inputs.day_offset)).date()
    period_start = datetime.combine(report_day, time.min, tzinfo=UTC)
    period_end = datetime.combine(report_day, time.max, tzinfo=UTC)
    return WorkflowContext(
        run_id=run_id,
        period_start=period_start,
        period_end=period_end,
        date_str=period_start.strftime("%Y-%m-%d"),
        report_completeness="partial" if inputs.day_offset == 0 else "complete",
        organization_ids=inputs.organization_ids,
    )


@workflow.defn(name="run-usage-reports")
class RunUsageReportsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunUsageReportsInputs:
        loaded = json.loads(inputs[0])
        return RunUsageReportsInputs(**loaded)

    @workflow.run
    async def run(self, inputs: RunUsageReportsInputs) -> dict:
        if inputs.day_offset < 0:
            # A negative offset (manual-trigger typo) would report a future,
            # empty day and mark it "complete" for billing. Fail fast;
            # non_retryable so the schedule's retry policy doesn't re-run a
            # validation error.
            raise ApplicationError(f"day_offset must be >= 0, got {inputs.day_offset}", non_retryable=True)
        started_at = workflow.now()
        status = "FAILED"
        try:
            ctx = build_context(inputs, run_id=workflow.info().run_id, now=workflow.now())
            workflow.logger.info(
                "Starting usage reports workflow",
                extra={
                    "run_id": ctx.run_id,
                    "date_str": ctx.date_str,
                    "report_completeness": ctx.report_completeness,
                    "period_start": ctx.period_start.isoformat(),
                    "period_end": ctx.period_end.isoformat(),
                    "spec_count": len(QUERIES),
                },
            )

            # Run the gather queries with bounded concurrency. We don't want
            # ~40 simultaneous heavy queries hitting ClickHouse / Postgres,
            # but a small batch shortens wall-clock substantially without
            # overwhelming the databases.
            sem = asyncio.Semaphore(QUERY_CONCURRENCY)

            async def _run_with_sem(spec: QuerySpec) -> RunQueryToS3Result:
                async with sem:
                    return await self._run_query(ctx, spec)

            query_results: list[RunQueryToS3Result] = list(
                await asyncio.gather(*(_run_with_sem(spec) for spec in QUERIES))
            )

            agg = await workflow.execute_activity(
                aggregate_and_chunk_org_reports,
                AggregateInputs(ctx=ctx, query_results=query_results),
                start_to_close_timeout=timedelta(minutes=60),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(seconds=30),
                ),
                heartbeat_timeout=timedelta(minutes=5),
            )

            await workflow.execute_activity(
                enqueue_pointer_message,
                EnqueuePointerInputs(ctx=ctx, aggregate=agg),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=5,
                    initial_interval=timedelta(seconds=10),
                ),
                heartbeat_timeout=timedelta(minutes=1),
            )

            # Intentionally NOT cleaning up the per-query intermediates yet —
            # we want them around in S3 for debugging while we validate the
            # new flow. Re-enable once we trust the pipeline:
            #
            # await workflow.execute_activity(
            #     cleanup_intermediates,
            #     CleanupInputs(ctx=ctx, query_keys=[r.s3_key for r in query_results]),
            #     start_to_close_timeout=timedelta(minutes=10),
            #     retry_policy=common.RetryPolicy(maximum_attempts=3),
            #     heartbeat_timeout=timedelta(minutes=2),
            # )

            workflow.logger.info(
                "Usage reports workflow complete",
                extra={
                    "run_id": ctx.run_id,
                    "total_orgs": agg.total_orgs,
                    "total_orgs_with_usage": agg.total_orgs_with_usage,
                    "chunk_count": len(agg.chunk_keys),
                    "run_prefix": run_prefix(ctx),
                },
            )

            status = "COMPLETED"
            return agg.model_dump()
        except asyncio.CancelledError:
            status = "CANCELLED"
            raise
        except Exception as err:
            workflow.logger.exception("Usage reports workflow failed", extra={"error": str(err)})
            capture_exception(err)
            raise
        finally:
            # Record exactly once, whichever way the run ends. Best-effort: a
            # metric-layer failure must not fail a successful run or mask the
            # original error.
            try:
                get_workflow_finished_metric(status=status).add(1)
                record_workflow_latency(workflow.now() - started_at, status=status)
            except Exception:
                workflow.logger.warning("Failed to record usage-reports workflow metrics", exc_info=True)

    async def _run_query(self, ctx: WorkflowContext, spec: QuerySpec) -> RunQueryToS3Result:
        return await workflow.execute_activity(
            run_query_to_s3,
            RunQueryToS3Inputs(ctx=ctx, query_name=spec.name),
            start_to_close_timeout=timedelta(minutes=spec.timeout_minutes),
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
            ),
            heartbeat_timeout=timedelta(minutes=2),
            summary=spec.name,
        )
