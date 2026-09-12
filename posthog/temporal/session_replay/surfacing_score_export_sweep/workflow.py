"""Daily tick: plan the (day × hash bucket) fan-out, export all partitions in parallel.
Failed partitions don't fail the tick — deterministic keys mean the next run rewrites them."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    EXPORT_PARTITION_ACTIVITY_TIMEOUT,
    EXPORT_PARTITION_HEARTBEAT_TIMEOUT,
    EXPORT_PARTITION_MAX_ATTEMPTS,
    LIST_PARTITIONS_ACTIVITY_TIMEOUT,
    MAX_CONCURRENT_EXPORT_PARTITIONS,
    MAX_ENCRYPTED_PAGES_PER_RUN,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    EncryptedScoreExport,
    EncryptedScoreManifest,
    EncryptedScorePage,
    EncryptedScorePlanInput,
    ExportPartitionResult,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
    ExportScoresSweepResult,
)

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
        export_encrypted_scores_page_activity,
        export_scores_partition_activity,
        list_export_partitions_activity,
        plan_encrypted_score_ranges_activity,
        publish_encrypted_score_manifest_activity,
    )
    from posthog.temporal.session_replay.surfacing_score_export_sweep.metrics import record_tick_summary


_PATCH_BOUNDED_PARTITION_FANOUT = "surfacing-score-export-bounded-partition-fanout"


@workflow.defn(name=WORKFLOW_NAME)
class ExportSurfacingScoresWorkflow(PostHogWorkflow):
    inputs_cls = ExportScoresSweepInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: ExportScoresSweepInputs) -> ExportScoresSweepResult:
        plan = await workflow.execute_activity(
            list_export_partitions_activity,
            inputs,
            start_to_close_timeout=LIST_PARTITIONS_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if plan.disabled_reason is not None:
            workflow.logger.warning(
                "surfacing_score_export_sweep.disabled", extra={"disabled_reason": plan.disabled_reason}
            )
            return ExportScoresSweepResult(disabled_reason=plan.disabled_reason)

        if not plan.partitions:
            workflow.logger.info("surfacing_score_export_sweep.no_work")
            return ExportScoresSweepResult()

        # Activity dispatch is recorded in Temporal history, so gate this change for deterministic replay.
        # The schedule timeout covers the retry budget for every bounded wave.
        concurrency = len(plan.partitions)
        if workflow.patched(_PATCH_BOUNDED_PARTITION_FANOUT):
            concurrency = min(MAX_CONCURRENT_EXPORT_PARTITIONS, concurrency)

        semaphore = asyncio.Semaphore(concurrency)

        async def _export_with_semaphore(spec: ExportPartitionSpec) -> ExportPartitionResult:
            async with semaphore:
                return await self._export_partition(spec)

        results = await asyncio.gather(
            *(_export_with_semaphore(spec) for spec in plan.partitions),
            return_exceptions=True,
        )
        return _summarize(plan.partitions, results)

    async def _export_partition(self, spec: ExportPartitionSpec) -> ExportPartitionResult:
        paged = workflow.patched("ai-research-encrypted-score-pages") and spec.encrypted_enabled
        result = await workflow.execute_activity(
            export_scores_partition_activity,
            replace(spec, legacy_only=True) if paged else spec,
            start_to_close_timeout=EXPORT_PARTITION_ACTIVITY_TIMEOUT,
            heartbeat_timeout=EXPORT_PARTITION_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(
                maximum_attempts=EXPORT_PARTITION_MAX_ATTEMPTS,
                non_retryable_error_types=[
                    "PseudonymKeyNotConfiguredError",
                    "PseudonymKeyFingerprintMismatchError",
                ],
            ),
        )
        if paged:
            export_id = f"{workflow.info().start_time.strftime('%Y%m%dT%H%M%S%f')}-{workflow.info().run_id}"
            exported = await workflow.execute_child_workflow(
                ExportEncryptedScoresWorkflow.run,
                EncryptedScoreExport(partition=spec, export_id=export_id),
                id=f"ai-research-score-export/{export_id}/{spec.day}/{spec.chunk_id}",
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            result.rows += exported.rows
            result.bytes_written += exported.bytes_written
        return result


@workflow.defn(name="ai-research-encrypted-score-export")
class ExportEncryptedScoresWorkflow(PostHogWorkflow):
    inputs_cls = EncryptedScoreExport

    @workflow.run
    async def run(self, inputs: EncryptedScoreExport) -> ExportPartitionResult:
        session_months = set(inputs.session_months)
        month_page_counts = dict(inputs.month_page_counts)
        cursor = inputs.cursor
        boundaries = list(inputs.boundaries)
        needs_plan = inputs.needs_plan
        pages = inputs.pages
        rows = inputs.rows
        bytes_written = inputs.bytes_written
        while boundaries or needs_plan:
            if not boundaries:
                plan = await workflow.execute_activity(
                    plan_encrypted_score_ranges_activity,
                    EncryptedScorePlanInput(partition=inputs.partition, cursor=cursor),
                    start_to_close_timeout=EXPORT_PARTITION_ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=EXPORT_PARTITION_MAX_ATTEMPTS),
                )
                boundaries = list(plan.boundaries)
                needs_plan = plan.has_more
                if not boundaries:
                    break
            upper = boundaries[0]
            exported = await workflow.execute_activity(
                export_encrypted_scores_page_activity,
                EncryptedScorePage(
                    partition=inputs.partition, export_id=inputs.export_id, page=pages, cursor=cursor, upper=upper
                ),
                start_to_close_timeout=EXPORT_PARTITION_ACTIVITY_TIMEOUT,
                heartbeat_timeout=EXPORT_PARTITION_HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=EXPORT_PARTITION_MAX_ATTEMPTS),
            )
            session_months.update(exported.session_months)
            for month in exported.session_months:
                month_page_counts[month] = month_page_counts.get(month, 0) + 1
            bytes_written += exported.bytes_written
            rows += exported.rows
            pages += 1
            if exported.next_page is not None:
                cursor = exported.next_page.cursor
            else:
                cursor = boundaries.pop(0)
            if pages - inputs.pages >= MAX_ENCRYPTED_PAGES_PER_RUN and (boundaries or needs_plan):
                workflow.continue_as_new(
                    replace(
                        inputs,
                        cursor=cursor,
                        boundaries=boundaries,
                        needs_plan=needs_plan,
                        pages=pages,
                        rows=rows,
                        bytes_written=bytes_written,
                        session_months=sorted(session_months),
                        month_page_counts=month_page_counts,
                    )
                )
        await workflow.execute_activity(
            publish_encrypted_score_manifest_activity,
            EncryptedScoreManifest(
                partition=inputs.partition,
                export_id=inputs.export_id,
                pages=pages,
                session_months=sorted(session_months),
                month_page_counts=month_page_counts,
            ),
            start_to_close_timeout=LIST_PARTITIONS_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=EXPORT_PARTITION_MAX_ATTEMPTS),
        )
        return ExportPartitionResult(
            day=inputs.partition.day, chunk_id=inputs.partition.chunk_id, rows=rows, bytes_written=bytes_written
        )


def _summarize(
    partitions: list[ExportPartitionSpec], results: list[ExportPartitionResult | BaseException]
) -> ExportScoresSweepResult:
    summary = ExportScoresSweepResult(partitions_dispatched=len(partitions))
    for r in results:
        if isinstance(r, asyncio.CancelledError):
            raise r
        if isinstance(r, BaseException):
            summary.partitions_failed += 1
            workflow.logger.warning(
                "surfacing_score_export_sweep.partition_failed",
                extra={"error": str(r), "error_type": type(r).__name__},
            )
            continue
        summary.total_rows += r.rows
    workflow.logger.info(
        "surfacing_score_export_sweep.tick_done",
        extra={
            "partitions_dispatched": summary.partitions_dispatched,
            "partitions_failed": summary.partitions_failed,
            "total_rows": summary.total_rows,
        },
    )
    record_tick_summary(
        partitions_dispatched=summary.partitions_dispatched,
        partitions_failed=summary.partitions_failed,
        total_rows=summary.total_rows,
    )
    return summary
