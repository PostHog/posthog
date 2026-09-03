"""Parent workflow for session surfacing scoring.

Per tick (driven by `schedule.py`):
    1. `list_chunks_activity` plans the fan-out — N deterministic hash-partitioned
       chunks, each carrying a `(chunk_id, of_chunks, chunk_size)` spec only.
    2. Chunks are dispatched via `asyncio.gather` behind a semaphore, so at most
       `MAX_CONCURRENT_SCORE_CHUNKS` run at once and the rest start as slots free.
       Each `score_chunk_activity` is fully self-contained (fetch + predict +
       write happen inside one activity).

The workflow stays tiny on purpose:
    * No per-session work in the workflow code path (workflow CPU is precious).
    * Inputs/outputs are summary counts only — the actual scores are written
      to ClickHouse from inside the activity, never returned through the
      workflow boundary (Temporal's 2 MiB payload limit).
    * Idempotent on retry — the CH `HAVING IS NULL` filter inside each chunk
      activity skips already-scored sessions automatically.
"""

from __future__ import annotations

import asyncio

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import (
    LIST_CHUNKS_ACTIVITY_TIMEOUT,
    MAX_CONCURRENT_SCORE_CHUNKS,
    SCORE_CHUNK_ACTIVITY_TIMEOUT,
    SCORE_CHUNK_HEARTBEAT_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.types import (
    ChunkResult,
    ChunkSpec,
    ScoreSessionsBatchInputs,
    ScoreSessionsBatchResult,
)

# Activity functions are referenced through `workflow.execute_activity`'s string
# name so Django doesn't need to be reachable from the workflow sandbox.
with workflow.unsafe.imports_passed_through():
    from posthog.temporal.session_replay.surfacing_scoring_sweep.activities import (
        list_chunks_activity,
        score_chunk_activity,
    )
    from posthog.temporal.session_replay.surfacing_scoring_sweep.metrics import record_tick_summary


_PATCH_BOUNDED_CHUNK_FANOUT = "surfacing-scoring-bounded-chunk-fanout"


@workflow.defn(name=WORKFLOW_NAME)
class ScoreSessionsBatchWorkflow(PostHogWorkflow):
    """One tick of the scoring pipeline."""

    inputs_cls = ScoreSessionsBatchInputs
    # Input dataclass is empty, so allow starting with no inputs.
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: ScoreSessionsBatchInputs) -> ScoreSessionsBatchResult:
        plan = await workflow.execute_activity(
            list_chunks_activity,
            inputs,
            start_to_close_timeout=LIST_CHUNKS_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(
                maximum_attempts=2,
            ),
        )

        if not plan.chunks:
            workflow.logger.info(
                "surfacing_scoring_sweep.no_work", extra={"estimated": plan.estimated_unscored_sessions}
            )
            return ScoreSessionsBatchResult()

        # Activity dispatch order is recorded in Temporal history, so gate the bound for
        # deterministic replay of runs that started before it.
        semaphore = asyncio.Semaphore(
            MAX_CONCURRENT_SCORE_CHUNKS if workflow.patched(_PATCH_BOUNDED_CHUNK_FANOUT) else len(plan.chunks)
        )

        async def _score_with_semaphore(spec: ChunkSpec) -> ChunkResult:
            async with semaphore:
                return await self._score_chunk(spec)

        results = await asyncio.gather(
            *(_score_with_semaphore(spec) for spec in plan.chunks),
            return_exceptions=True,
        )

        return _summarize(plan.chunks, results)

    async def _score_chunk(self, spec: ChunkSpec) -> ChunkResult:
        return await workflow.execute_activity(
            score_chunk_activity,
            spec,
            start_to_close_timeout=SCORE_CHUNK_ACTIVITY_TIMEOUT,
            heartbeat_timeout=SCORE_CHUNK_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(
                # Single attempt: a retry after a 4-min activity timeout cannot
                # fit inside the 4m30s workflow budget, so it would be killed
                # mid-flight by workflow expiry anyway. Failed chunks stay NULL
                # in CH and the next 5-min tick is the natural retry.
                maximum_attempts=1,
                non_retryable_error_types=["FeatureValidationError", "ScoreRangeError", "ModelNotConfiguredError"],
            ),
        )


def _summarize(chunks: list[ChunkSpec], results: list[ChunkResult | BaseException]) -> ScoreSessionsBatchResult:
    """Roll per-chunk results up to a tick-level summary.

    Failed chunks are counted but don't bring the workflow down — their
    sessions stay NULL in CH and pick up on the next 5-min tick.
    """
    summary = ScoreSessionsBatchResult(chunks_dispatched=len(chunks))
    for r in results:
        if isinstance(r, BaseException):
            summary.chunks_failed += 1
            if isinstance(r, ActivityError):
                workflow.logger.warning(
                    "surfacing_scoring_sweep.chunk_activity_failed",
                    extra={"error": str(r)},
                )
            continue
        summary.total_scored += r.scored
        summary.total_fetched += r.fetched
    workflow.logger.info(
        "surfacing_scoring_sweep.tick_done",
        extra={
            "chunks_dispatched": summary.chunks_dispatched,
            "chunks_failed": summary.chunks_failed,
            "total_scored": summary.total_scored,
            "total_fetched": summary.total_fetched,
        },
    )
    record_tick_summary(
        total_scored=summary.total_scored,
        total_fetched=summary.total_fetched,
        chunks_failed=summary.chunks_failed,
    )
    return summary
