"""Temporal activities for the usage reports workflow.

Each activity is a thin wrapper that delegates to either the public
`posthog.tasks.usage_report` facade (org-report aggregation, instance
metadata) or the local `aggregator` / `storage` modules. Heavy logic lives
elsewhere so these stay easy to read and mock in tests.
"""

import json
import time
import asyncio
from typing import Any

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.tasks.usage_report import get_instance_metadata
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.metrics import ExecutionTimeRecorder
from posthog.temporal.usage_report.aggregator import (
    batched,
    build_manifest,
    build_org_reports,
    filter_org_reports,
    filter_orgs_with_usage,
    get_org_user_counts,
    iter_chunk_lines,
    load_all_data,
    sort_org_reports,
)
from posthog.temporal.usage_report.metrics import (
    USAGE_REPORTS_AGGREGATE_LATENCY,
    USAGE_REPORTS_ENQUEUE_LATENCY,
    USAGE_REPORTS_QUERY_LATENCY,
    get_pointer_messages_sent_metric,
    record_aggregate_output,
    record_pointer_sent_timestamp,
)
from posthog.temporal.usage_report.queries import QUERY_INDEX
from posthog.temporal.usage_report.storage import (
    bucket,
    chunk_key,
    chunks_prefix,
    delete_keys,
    manifest_key,
    queries_key,
    write_json,
    write_jsonl_chunk_gzip,
)
from posthog.temporal.usage_report.types import (
    AggregateInputs,
    AggregateResult,
    CleanupInputs,
    EnqueuePointerInputs,
    RunQueryToS3Inputs,
    RunQueryToS3Result,
)
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

CHUNK_SIZE_ORGS = 50_000
SQS_POINTER_VERSION = 2

# Separate SQS queue for v2 messages so the existing per-org `usage_reports`
# stream and the new pointer stream don't clash while both flows run side by
# side. Billing opts in by reading from this queue once it's ready.
SQS_QUEUE_NAME = "usage_reports_v2"


@activity.defn(name="run-usage-report-query")
async def run_query_to_s3(inputs: RunQueryToS3Inputs) -> RunQueryToS3Result:
    """Run one gather query and persist the raw result to S3 as JSON.

    Each invocation maps 1:1 to a `QuerySpec` in the registry; the returned
    `s3_key` is the only thing that flows back into the workflow (so we stay
    well under Temporal's payload limits).
    """
    async with Heartbeater():
        with ExecutionTimeRecorder(
            USAGE_REPORTS_QUERY_LATENCY,
            description="Run one usage-reports gather query and write its result to S3.",
            histogram_attributes={"query_name": inputs.query_name},
        ):
            spec = QUERY_INDEX[inputs.query_name]

            # Use the pooled variant so concurrent query activities on the same
            # worker actually run in parallel. The default thread_sensitive=True
            # serializes everything onto a single shared thread, defeating the
            # bounded fan-out in the workflow.
            @database_sync_to_async_pool
            def run() -> Any:
                # Snapshot specs ignore the period (they read current state);
                # period specs filter on (begin, end). The signature is enforced
                # by `QuerySpec.fn`'s union type and validated in registry tests.
                if spec.kind == "snapshot":
                    return spec.fn()  # type: ignore[call-arg]
                return spec.fn(inputs.ctx.period_start, inputs.ctx.period_end)  # type: ignore[call-arg]

            started = time.monotonic()
            result = await run()
            duration_ms = int((time.monotonic() - started) * 1000)

            key = queries_key(inputs.ctx, inputs.query_name)
            await sync_to_async(write_json)(key, result)

            return RunQueryToS3Result(
                query_name=inputs.query_name,
                s3_key=key,
                duration_ms=duration_ms,
            )


@activity.defn(name="aggregate-and-chunk-org-reports")
async def aggregate_and_chunk_org_reports(inputs: AggregateInputs) -> AggregateResult:
    """Read per-query S3 files, build org reports, and write JSONL chunks.

    The aggregation logic is delegated to `aggregator` so this activity reads
    as a sequence of named steps. Output is byte-compatible with the existing
    Celery flow so we can validate parity before billing cuts over.
    """
    async with Heartbeater():
        with ExecutionTimeRecorder(
            USAGE_REPORTS_AGGREGATE_LATENCY,
            description="Aggregate per-query S3 results into org-report chunks.",
        ):
            all_data = await sync_to_async(load_all_data)(inputs.query_results)

            @database_sync_to_async
            def aggregate_per_org() -> dict[str, Any]:
                # Bulk-fetch membership counts once instead of letting the org
                # builder issue a Postgres count() per organization. See
                # `aggregator.build_org_reports` for the rationale.
                org_user_counts = get_org_user_counts()
                org_reports = build_org_reports(all_data, inputs.ctx.period_start, org_user_counts)
                org_reports = filter_org_reports(org_reports, inputs.ctx.organization_ids)
                return org_reports

            org_reports = await aggregate_per_org()

            instance_metadata = await database_sync_to_async(get_instance_metadata)(
                (inputs.ctx.period_start, inputs.ctx.period_end)
            )

            # TODO(usage-reports-v2): re-enable PostHog product-analytics
            # `capture_report` per organization once the billing path is validated.
            # That call updates organization group properties (member/project/dashboard
            # counts) used by customer.io segmentation and emits the
            # "organization usage report" event consumed for internal analytics.

            total_orgs = len(org_reports)
            orgs_with_usage = filter_orgs_with_usage(org_reports)
            total_orgs_with_usage = len(orgs_with_usage)

            sorted_reports = sort_org_reports(orgs_with_usage)
            batches = list(enumerate(batched(sorted_reports, CHUNK_SIZE_ORGS)))
            chunk_keys: list[str] = [chunk_key(inputs.ctx, index) for index, _ in batches]

            # Each chunk is an independent S3 object, so fan the encode+gzip+PUT
            # out across the thread pool. `thread_sensitive=False` opts out of
            # the shared-thread default so the PUTs run concurrently — boto3
            # releases the GIL during the network call, so they genuinely
            # overlap on the wire. Using `asyncio.TaskGroup` (over
            # `asyncio.gather`) means a single failed upload doesn't cancel
            # in-flight peer uploads mid-PUT; the group waits for every
            # started task to finish or fail before re-raising, so Temporal
            # retries from a clean state.
            def write_chunk(key: str, batch: list[Any]) -> None:
                write_jsonl_chunk_gzip(key, iter_chunk_lines(batch, instance_metadata))

            async with asyncio.TaskGroup() as tg:
                for index, batch in batches:
                    tg.create_task(sync_to_async(write_chunk, thread_sensitive=False)(chunk_keys[index], batch))

            manifest = build_manifest(
                inputs.ctx,
                chunk_keys=chunk_keys,
                total_orgs=total_orgs,
                total_orgs_with_usage=total_orgs_with_usage,
                region=get_instance_region() or "",
                version=SQS_POINTER_VERSION,
            )
            m_key = manifest_key(inputs.ctx)
            await sync_to_async(write_json)(m_key, manifest.model_dump(mode="json"))

            return AggregateResult(
                chunk_keys=chunk_keys,
                manifest_key=m_key,
                total_orgs=total_orgs,
                total_orgs_with_usage=total_orgs_with_usage,
            )


@activity.defn(name="usage-reports-enqueue-pointer-message")
async def enqueue_pointer_message(inputs: EnqueuePointerInputs) -> None:
    """Send a single SQS pointer message to the v2 billing queue.

    Body is plain JSON describing where to find the gzipped chunks; billing
    reads the actual usage data from S3.
    """
    with ExecutionTimeRecorder(
        USAGE_REPORTS_ENQUEUE_LATENCY,
        description="Send the usage-reports v2 SQS pointer message to billing.",
    ) as recorder:
        if not settings.EE_AVAILABLE:
            recorder.set_status("SKIPPED")
            try:
                get_pointer_messages_sent_metric(outcome="skipped_no_ee").add(1)
            except Exception as err:
                await logger.awarning("usage_reports.metrics.record_failed", error=str(err))
            await logger.awarning("usage_reports.sqs.skipped_no_ee")
            return

        pointer = {
            "version": SQS_POINTER_VERSION,
            "run_id": inputs.ctx.run_id,
            "date": inputs.ctx.date_str,
            "period_start": inputs.ctx.period_start.isoformat(),
            "period_end": inputs.ctx.period_end.isoformat(),
            # "complete" tells billing the reported day was already over when
            # queried — its signal to treat the numbers as final for that date.
            "report_completeness": inputs.ctx.report_completeness,
            "region": get_instance_region(),
            "site_url": settings.SITE_URL,
            "bucket": bucket(),
            "manifest_key": inputs.aggregate.manifest_key,
            "chunk_prefix": chunks_prefix(inputs.ctx) + "/",
            "chunk_count": len(inputs.aggregate.chunk_keys),
            "total_orgs": inputs.aggregate.total_orgs,
            "total_orgs_with_usage": inputs.aggregate.total_orgs_with_usage,
        }
        # Omit the key for legacy contexts (field absent pre-deploy); billing
        # reads it with `.get(...)` and skips the flow-latency metric when None.
        if inputs.ctx.workflow_started_at is not None:
            pointer["workflow_started_at"] = inputs.ctx.workflow_started_at.isoformat()

        @sync_to_async
        def send() -> None:
            from ee.sqs.SQSProducer import get_sqs_producer

            producer = get_sqs_producer(SQS_QUEUE_NAME)
            if producer is None:
                raise RuntimeError(f"SQS producer for queue '{SQS_QUEUE_NAME}' is not configured")
            response = producer.send_message(
                message_body=json.dumps(pointer, separators=(",", ":")),
                message_attributes={
                    "content_type": "application/json",
                    "schema_version": str(SQS_POINTER_VERSION),
                    "run_id": inputs.ctx.run_id,
                },
            )
            if response is None:
                raise RuntimeError("SQS send_message returned no response")

        await send()
        # Best-effort from here down: the pointer is already delivered, so a
        # metric-layer failure must not fail the activity — Temporal would
        # retry it and send billing a duplicate pointer.
        try:
            get_pointer_messages_sent_metric(outcome="sent").add(1)
            record_aggregate_output(
                total_orgs=inputs.aggregate.total_orgs,
                total_orgs_with_usage=inputs.aggregate.total_orgs_with_usage,
                chunk_count=len(inputs.aggregate.chunk_keys),
            )
            record_pointer_sent_timestamp()
        except Exception as err:
            await logger.awarning("usage_reports.metrics.record_failed", error=str(err))


@activity.defn(name="usage-reports-cleanup-intermediates")
async def cleanup_intermediates(inputs: CleanupInputs) -> int:
    """Delete the per-query S3 intermediates. Chunks and manifest are kept
    so the billing consumer can read them after the SQS pointer arrives.
    """
    return await sync_to_async(delete_keys)(inputs.query_keys)
