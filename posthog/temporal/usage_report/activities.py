"""Temporal activities for the usage reports workflow.

Each activity is a thin wrapper that delegates to either the public
`posthog.tasks.usage_report` facade (org-report aggregation, instance
metadata) or the local `aggregator` / `storage` modules. Heavy logic lives
elsewhere so these stay easy to read and mock in tests.
"""

import json
import time
from typing import Any

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.sync import database_sync_to_async
from posthog.tasks.usage_report import build_org_reports, get_instance_metadata
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.usage_report.aggregator import (
    batched,
    build_manifest,
    filter_org_reports,
    iter_chunk_lines,
    load_all_data,
    sort_org_reports,
)
from posthog.temporal.usage_report.queries import QUERY_INDEX
from posthog.temporal.usage_report.storage import (
    bucket,
    chunk_key,
    chunks_prefix,
    delete_keys,
    manifest_key,
    queries_key,
    streamed_jsonl_gzip_writer,
    write_json,
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

CHUNK_SIZE_ORGS = 10_000
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
        spec = QUERY_INDEX[inputs.query_name]

        @database_sync_to_async
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
        all_data = await sync_to_async(load_all_data)(inputs.query_results)

        @database_sync_to_async
        def aggregate_per_org() -> dict[str, Any]:
            org_reports = build_org_reports(all_data, inputs.ctx.period_start)
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

        sorted_reports = sort_org_reports(org_reports)
        chunk_keys: list[str] = []
        total_orgs_with_usage = 0

        for index, batch in enumerate(batched(sorted_reports, CHUNK_SIZE_ORGS)):
            key = chunk_key(inputs.ctx, index)
            async with streamed_jsonl_gzip_writer(key) as writer:
                for line, has_usage in iter_chunk_lines(batch, instance_metadata):
                    writer.write(line)
                    if has_usage:
                        total_orgs_with_usage += 1
            chunk_keys.append(key)

        manifest = build_manifest(
            inputs.ctx,
            chunk_keys=chunk_keys,
            total_orgs=len(org_reports),
            total_orgs_with_usage=total_orgs_with_usage,
            region=get_instance_region() or "",
            version=SQS_POINTER_VERSION,
        )
        m_key = manifest_key(inputs.ctx)
        await sync_to_async(write_json)(m_key, manifest.model_dump(mode="json"))

        return AggregateResult(
            chunk_keys=chunk_keys,
            manifest_key=m_key,
            total_orgs=len(org_reports),
            total_orgs_with_usage=total_orgs_with_usage,
        )


@activity.defn(name="usage-reports-enqueue-pointer-message")
async def enqueue_pointer_message(inputs: EnqueuePointerInputs) -> None:
    """Send a single SQS pointer message to the v2 billing queue.

    Body is plain JSON describing where to find the gzipped chunks; billing
    reads the actual usage data from S3.
    """
    if not settings.EE_AVAILABLE:
        await logger.awarning("usage_reports.sqs.skipped_no_ee")
        return

    pointer = {
        "version": SQS_POINTER_VERSION,
        "run_id": inputs.ctx.run_id,
        "date": inputs.ctx.date_str,
        "period_start": inputs.ctx.period_start.isoformat(),
        "period_end": inputs.ctx.period_end.isoformat(),
        "region": get_instance_region(),
        "site_url": settings.SITE_URL,
        "bucket": bucket(),
        "manifest_key": inputs.aggregate.manifest_key,
        "chunk_prefix": chunks_prefix(inputs.ctx) + "/",
        "chunk_count": len(inputs.aggregate.chunk_keys),
        "total_orgs": inputs.aggregate.total_orgs,
        "total_orgs_with_usage": inputs.aggregate.total_orgs_with_usage,
    }

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


@activity.defn(name="usage-reports-cleanup-intermediates")
async def cleanup_intermediates(inputs: CleanupInputs) -> int:
    """Delete the per-query S3 intermediates. Chunks and manifest are kept
    so the billing consumer can read them after the SQS pointer arrives.
    """
    return await sync_to_async(delete_keys)(inputs.query_keys)
