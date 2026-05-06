"""Temporal workflow that aggregates daily usage data and publishes it to S3
for the billing service.

The workflow runs ~50 gather queries (each as its own retriable activity),
then a single aggregation activity reads them all back from S3, builds one
`FullUsageReport` dict per organization, and writes those reports as gzipped
JSONL chunks (≤10k orgs each) plus a manifest. A final
`enqueue_pointer_message` activity sends a single SQS message to the billing
service pointing at the S3 prefix; billing reads the chunks from S3 instead
of receiving 50k+ per-org SQS messages.

This replaces the per-org SQS fan-out in
`posthog/tasks/usage_report.py:send_all_org_usage_reports`. The Celery task
remains in production until billing migrates to consume the S3 layout.
"""

import json
from datetime import datetime, timedelta
from typing import Optional

from dateutil import parser
from temporalio import common, workflow

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.usage_report.activities import (
    aggregate_and_chunk_org_reports,
    enqueue_pointer_message,
    run_query_to_s3,
)
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
from posthog.utils import get_previous_day


def build_context(inputs: RunUsageReportsInputs, run_id: str, now: Optional[datetime] = None) -> WorkflowContext:
    """Compute the period and S3 layout context. Pure function so it's safe
    to call from the workflow body (no real-time access).
    """
    at_date = parser.parse(inputs.at) if inputs.at else None
    if at_date is None and now is not None:
        at_date = now
    period_start, period_end = get_previous_day(at=at_date)
    return WorkflowContext(
        run_id=run_id,
        period_start=period_start,
        period_end=period_end,
        date_str=period_start.strftime("%Y-%m-%d"),
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
        try:
            ctx = build_context(inputs, run_id=workflow.info().run_id, now=workflow.now())
            workflow.logger.info(
                "Starting usage reports workflow",
                extra={
                    "run_id": ctx.run_id,
                    "date_str": ctx.date_str,
                    "period_start": ctx.period_start.isoformat(),
                    "period_end": ctx.period_end.isoformat(),
                    "spec_count": len(QUERIES),
                },
            )

            # Run the gather queries serially. Even though Temporal could run
            # them in parallel, we deliberately stagger them so we don't pile
            # ~40 simultaneous heavy queries onto ClickHouse / Postgres at
            # once — the daily report is not latency-sensitive, and giving
            # the databases breathing room matters more than wall-clock.
            query_results: list[RunQueryToS3Result] = []
            for spec in QUERIES:
                query_results.append(await self._run_query(ctx, spec))

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

            return agg.model_dump()
        except Exception as err:
            workflow.logger.exception("Usage reports workflow failed", extra={"error": str(err)})
            capture_exception(err)
            raise

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
        )
