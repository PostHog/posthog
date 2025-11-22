"""
Batch trace summarization workflow for LLMA.

This workflow runs daily to:
1. Sample N recent traces from the past day
2. Generate text representations and summaries for each trace
3. Store summaries as $ai_trace_summary events in ClickHouse
4. Generate embeddings for summaries and store in document_embeddings table

The summaries and embeddings serve as inputs for clustering and semantic search.
"""

from datetime import timedelta
from typing import Any

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_WINDOW_MINUTES,
    EMBED_TIMEOUT_SECONDS,
    EMIT_EVENTS_TIMEOUT_SECONDS,
    FETCH_HIERARCHY_TIMEOUT_SECONDS,
    GENERATE_SUMMARY_TIMEOUT_SECONDS,
    SAMPLE_TIMEOUT_SECONDS,
    WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_summarization.embedding import embed_summaries_activity
from posthog.temporal.llm_analytics.trace_summarization.events import emit_trace_summary_events_activity
from posthog.temporal.llm_analytics.trace_summarization.fetching import fetch_trace_hierarchy_activity
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, TraceSummary
from posthog.temporal.llm_analytics.trace_summarization.sampling import query_traces_in_window_activity
from posthog.temporal.llm_analytics.trace_summarization.summarization import generate_summary_activity

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

    @temporalio.workflow.run
    async def run(self, inputs: BatchSummarizationInputs) -> dict[str, Any]:
        """Execute batch summarization workflow."""
        start_time = temporalio.workflow.now()
        batch_run_id = f"{inputs.team_id}_{start_time.isoformat()}"

        logger.info(
            "Starting batch trace summarization",
            team_id=inputs.team_id,
            max_traces=inputs.max_traces,
            batch_size=inputs.batch_size,
            mode=inputs.mode,
            window_minutes=inputs.window_minutes,
            batch_run_id=batch_run_id,
        )

        # Step 1: Query traces from window
        traces = await temporalio.workflow.execute_activity(
            query_traces_in_window_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=SAMPLE_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not traces:
            logger.info(
                "No traces found in window",
                team_id=inputs.team_id,
                window_minutes=inputs.window_minutes,
                batch_run_id=batch_run_id,
            )
            return {
                "batch_run_id": batch_run_id,
                "traces_queried": 0,
                "summaries_requested": 0,
                "summaries_failed": 0,
                "summaries_generated": 0,
                "events_emitted": 0,
                "embeddings_requested": 0,
                "embeddings_failed": 0,
            }

        # Step 2: Process traces in batches
        total_summaries_requested = 0
        total_summaries_failed = 0
        total_summaries_generated = 0
        total_events = 0
        total_embeddings_requested = 0
        total_embeddings_failed = 0

        for i in range(0, len(traces), inputs.batch_size):
            batch = traces[i : i + inputs.batch_size]
            batch_num = i // inputs.batch_size + 1

            logger.info(
                "Processing batch",
                batch_num=batch_num,
                batch_size=len(batch),
                team_id=inputs.team_id,
            )

            # Fetch trace hierarchies and generate summaries for this batch
            batch_summaries: list[TraceSummary] = []

            for trace_info in batch:
                total_summaries_requested += 1
                try:
                    # Fetch full trace data
                    trace_data = await temporalio.workflow.execute_activity(
                        fetch_trace_hierarchy_activity,
                        args=[
                            trace_info["trace_id"],
                            trace_info["team_id"],
                            trace_info["trace_timestamp"],
                        ],
                        schedule_to_close_timeout=timedelta(seconds=FETCH_HIERARCHY_TIMEOUT_SECONDS),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )

                    # Generate summary
                    summary = await temporalio.workflow.execute_activity(
                        generate_summary_activity,
                        args=[trace_data, inputs.team_id, inputs.mode, inputs.model],
                        schedule_to_close_timeout=timedelta(seconds=GENERATE_SUMMARY_TIMEOUT_SECONDS),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )

                    batch_summaries.append(summary)

                except Exception as e:
                    total_summaries_failed += 1
                    logger.exception(
                        "Failed to generate summary for trace",
                        trace_id=trace_info["trace_id"],
                        error=str(e),
                    )
                    # Continue with next trace

            # Step 3: Emit summary events for this batch
            if batch_summaries:
                events_count = await temporalio.workflow.execute_activity(
                    emit_trace_summary_events_activity,
                    args=[batch_summaries, inputs.team_id, batch_run_id],
                    schedule_to_close_timeout=timedelta(seconds=EMIT_EVENTS_TIMEOUT_SECONDS),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                # Step 4: Generate embeddings for this batch
                embedding_result = await temporalio.workflow.execute_activity(
                    embed_summaries_activity,
                    args=[batch_summaries, inputs.team_id, inputs.mode],
                    schedule_to_close_timeout=timedelta(seconds=EMBED_TIMEOUT_SECONDS),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                total_summaries_generated += len(batch_summaries)
                total_events += events_count
                total_embeddings_requested += embedding_result["embeddings_requested"]
                total_embeddings_failed += embedding_result["embeddings_failed"]

        end_time = temporalio.workflow.now()
        duration = (end_time - start_time).total_seconds()

        logger.info(
            "Batch trace summarization completed",
            team_id=inputs.team_id,
            batch_run_id=batch_run_id,
            traces_queried=len(traces),
            summaries_requested=total_summaries_requested,
            summaries_failed=total_summaries_failed,
            summaries_generated=total_summaries_generated,
            events_emitted=total_events,
            embeddings_requested=total_embeddings_requested,
            embeddings_failed=total_embeddings_failed,
            duration_seconds=duration,
        )

        return {
            "batch_run_id": batch_run_id,
            "traces_queried": len(traces),
            "summaries_requested": total_summaries_requested,
            "summaries_failed": total_summaries_failed,
            "summaries_generated": total_summaries_generated,
            "events_emitted": total_events,
            "embeddings_requested": total_embeddings_requested,
            "embeddings_failed": total_embeddings_failed,
            "duration_seconds": duration,
        }
