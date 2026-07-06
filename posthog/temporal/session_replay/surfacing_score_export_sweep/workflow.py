"""Parent workflow for the surfacing-score export sweep.

Per daily tick (driven by `schedule.py`):
    1. `list_export_partitions_activity` checks the export is configured and
       plans the (day × hash bucket) fan-out over the re-export window.
    2. All partitions are dispatched via `asyncio.gather`; each
       `export_scores_partition_activity` is fully self-contained
       (fetch + pseudonymize + Parquet + S3 put inside one activity).

Failed partitions don't fail the tick — deterministic object keys mean the
next daily run (or the re-export window) rewrites them.
"""

from __future__ import annotations

import asyncio

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    EXPORT_PARTITION_ACTIVITY_TIMEOUT,
    EXPORT_PARTITION_HEARTBEAT_TIMEOUT,
    LIST_PARTITIONS_ACTIVITY_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    ExportPartitionResult,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
    ExportScoresSweepResult,
)

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.session_replay.surfacing_score_export_sweep.activities import (
        export_scores_partition_activity,
        list_export_partitions_activity,
    )


@workflow.defn(name=WORKFLOW_NAME)
class ExportSurfacingScoresWorkflow(PostHogWorkflow):
    """One daily tick of the score export."""

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
            workflow.logger.warning("surfacing_score_export_sweep.disabled", disabled_reason=plan.disabled_reason)
            return ExportScoresSweepResult(disabled_reason=plan.disabled_reason)

        if not plan.partitions:
            workflow.logger.info("surfacing_score_export_sweep.no_work")
            return ExportScoresSweepResult()

        results = await asyncio.gather(
            *(self._export_partition(spec) for spec in plan.partitions),
            return_exceptions=True,
        )
        return _summarize(plan.partitions, results)

    async def _export_partition(self, spec: ExportPartitionSpec) -> ExportPartitionResult:
        return await workflow.execute_activity(
            export_scores_partition_activity,
            spec,
            start_to_close_timeout=EXPORT_PARTITION_ACTIVITY_TIMEOUT,
            heartbeat_timeout=EXPORT_PARTITION_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                non_retryable_error_types=[
                    "PseudonymKeyNotConfiguredError",
                    "PseudonymKeyFingerprintMismatchError",
                ],
            ),
        )


def _summarize(
    partitions: list[ExportPartitionSpec], results: list[ExportPartitionResult | BaseException]
) -> ExportScoresSweepResult:
    summary = ExportScoresSweepResult(partitions_dispatched=len(partitions))
    for r in results:
        if isinstance(r, BaseException):
            summary.partitions_failed += 1
            if isinstance(r, ActivityError):
                workflow.logger.warning("surfacing_score_export_sweep.partition_failed", error=str(r))
            continue
        summary.total_rows += r.rows
    workflow.logger.info(
        "surfacing_score_export_sweep.tick_done",
        partitions_dispatched=summary.partitions_dispatched,
        partitions_failed=summary.partitions_failed,
        total_rows=summary.total_rows,
    )
    return summary
