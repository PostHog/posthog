"""
Batch trace summarization workflow for LLMA.

This workflow runs on a schedule (e.g., hourly) to:
1. Sample N recent traces from a time window
2. Generate text representations and summaries for each trace
3. Store summaries as $ai_trace_summary events in ClickHouse
4. Generate embeddings for summaries and store in document_embeddings table

The summaries and embeddings serve as inputs for clustering and semantic search.
"""

import asyncio
from datetime import timedelta

import structlog
import temporalio

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_WINDOW_MINUTES,
    EMBED_TIMEOUT_SECONDS,
    GENERATE_SUMMARY_TIMEOUT_SECONDS,
    SAMPLE_TIMEOUT_SECONDS,
    WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_summarization.embedding import embed_summaries_from_events_activity
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, BatchSummarizationResult
from posthog.temporal.llm_analytics.trace_summarization.sampling import query_traces_in_window_activity
from posthog.temporal.llm_analytics.trace_summarization.summarization import generate_and_save_summary_activity

logger = structlog.get_logger(__name__)


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class BatchTraceSummarizationWorkflow(PostHogWorkflow):
    """
    Workflow for batch summarization of traces.

    Processes traces from a time window (e.g., last 60 minutes) up to a maximum count.
    Designed to run on a schedule (hourly) to keep summaries up to date.

    The workflow is idempotent - rerunning on the same window regenerates the same summaries.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchSummarizationInputs:
        """Parse workflow inputs from string list (for backward compatibility)."""
        return BatchSummarizationInputs(
            team_id=int(inputs[0]),
            max_traces=int(inputs[1]) if len(inputs) > 1 else DEFAULT_MAX_TRACES_PER_WINDOW,
            batch_size=int(inputs[2]) if len(inputs) > 2 else DEFAULT_BATCH_SIZE,
            mode=inputs[3] if len(inputs) > 3 else DEFAULT_MODE,
            window_minutes=int(inputs[4]) if len(inputs) > 4 else DEFAULT_WINDOW_MINUTES,
            window_start=inputs[5] if len(inputs) > 5 else None,
            window_end=inputs[6] if len(inputs) > 6 else None,
            model=inputs[7] if len(inputs) > 7 else None,
        )

    @staticmethod
    async def _process_trace(
        semaphore: asyncio.Semaphore,
        trace_info: dict,
        mode: str,
        batch_run_id: str,
        model: str | None,
    ):
        """Process a single trace with semaphore-controlled concurrency.

        Args:
            semaphore: Asyncio semaphore to limit concurrent activities
            trace_info: Dict containing trace_id, team_id, and trace_timestamp
            mode: Summary mode ('minimal' or 'detailed')
            batch_run_id: Unique identifier for this batch run
            model: Optional LLM model to use for summarization
        """
        async with semaphore:
            return await temporalio.workflow.execute_activity(
                generate_and_save_summary_activity,
                args=[
                    trace_info["trace_id"],
                    trace_info["team_id"],
                    trace_info["trace_timestamp"],
                    mode,
                    batch_run_id,
                    model,
                ],
                schedule_to_close_timeout=timedelta(seconds=GENERATE_SUMMARY_TIMEOUT_SECONDS),
                retry_policy=constants.SUMMARIZE_RETRY_POLICY,
            )

    @temporalio.workflow.run
    async def run(self, inputs: BatchSummarizationInputs) -> BatchSummarizationResult:
        """Execute batch summarization workflow."""
        start_time = temporalio.workflow.now()
        batch_run_id = f"{inputs.team_id}_{start_time.isoformat()}"

        # Step 1: Query traces from window
        trace_ids = await temporalio.workflow.execute_activity(
            query_traces_in_window_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=SAMPLE_TIMEOUT_SECONDS),
            retry_policy=constants.SAMPLE_RETRY_POLICY,
        )

        if not trace_ids:
            logger.info("No traces found in window", team_id=inputs.team_id, batch_run_id=batch_run_id)
            return BatchSummarizationResult(
                batch_run_id=batch_run_id,
                traces_queried=0,
                summaries_requested=0,
                summaries_failed=0,
                summaries_generated=0,
                events_emitted=0,
                embeddings_requested=0,
                embeddings_failed=0,
                duration_seconds=0.0,
            )

        # Step 2: Process all traces with concurrency control via semaphore
        # This avoids the convoy effect where fast tasks wait for slow ones in batches
        logger.info(
            "Starting batch summarization",
            team_id=inputs.team_id,
            batch_run_id=batch_run_id,
            traces_queried=len(trace_ids),
            batch_size=inputs.batch_size,
        )

        total_summaries_requested = len(trace_ids)
        total_embeddings_requested = 0
        total_embeddings_failed = 0

        # Create semaphore to limit concurrent activities
        semaphore = asyncio.Semaphore(inputs.batch_size)

        # Execute all traces in parallel with semaphore limiting concurrency
        tasks = [
            self._process_trace(
                semaphore=semaphore,
                trace_info=trace_info,
                mode=inputs.mode,
                batch_run_id=batch_run_id,
                model=inputs.model,
            )
            for trace_info in trace_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and collect successful trace IDs for embedding
        successful_trace_ids = []
        for trace_info, result in zip(trace_ids, results):
            if isinstance(result, Exception):
                logger.exception(
                    "Failed to generate and save summary for trace",
                    trace_id=trace_info["trace_id"],
                    batch_run_id=batch_run_id,
                    error=str(result),
                )
            else:
                successful_trace_ids.append(trace_info["trace_id"])

        total_summaries_generated = len(successful_trace_ids)
        total_summaries_failed = total_summaries_requested - total_summaries_generated

        # Step 3: Generate embeddings for all successful summaries
        if successful_trace_ids:
            # Wait for ClickHouse to ingest events before querying them
            logger.info(
                "Waiting for ClickHouse ingestion before embedding",
                team_id=inputs.team_id,
                batch_run_id=batch_run_id,
                trace_count=len(successful_trace_ids),
            )
            await asyncio.sleep(3)  # Give ClickHouse time to ingest events

            embedding_result = await temporalio.workflow.execute_activity(
                embed_summaries_from_events_activity,
                args=[successful_trace_ids, inputs.team_id, inputs.mode, start_time.isoformat()],
                schedule_to_close_timeout=timedelta(seconds=EMBED_TIMEOUT_SECONDS),
                retry_policy=constants.EMBED_RETRY_POLICY,
            )
            total_embeddings_requested += embedding_result["embeddings_requested"]
            total_embeddings_failed += embedding_result["embeddings_failed"]

            # Check if we got all expected embeddings
            if total_embeddings_requested < len(successful_trace_ids):
                logger.warning(
                    "Not all embeddings were generated",
                    team_id=inputs.team_id,
                    batch_run_id=batch_run_id,
                    expected=len(successful_trace_ids),
                    actual=total_embeddings_requested,
                )

        end_time = temporalio.workflow.now()
        duration = (end_time - start_time).total_seconds()

        # Check error rate and fail workflow if exceeds threshold
        error_rate = total_summaries_failed / total_summaries_requested if total_summaries_requested > 0 else 0
        if error_rate > constants.MAX_ERROR_RATE_THRESHOLD:
            raise RuntimeError(
                f"Workflow failed: error rate {error_rate:.1%} exceeds {constants.MAX_ERROR_RATE_THRESHOLD:.0%} threshold "
                f"({total_summaries_failed}/{total_summaries_requested} failed)"
            )

        return BatchSummarizationResult(
            batch_run_id=batch_run_id,
            traces_queried=len(trace_ids),
            summaries_requested=total_summaries_requested,
            summaries_failed=total_summaries_failed,
            summaries_generated=total_summaries_generated,
            events_emitted=total_summaries_generated,
            embeddings_requested=total_embeddings_requested,
            embeddings_failed=total_embeddings_failed,
            duration_seconds=duration,
        )
