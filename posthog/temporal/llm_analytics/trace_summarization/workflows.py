"""
Batch trace summarization workflow for LLMA.

This workflow runs daily to:
1. Sample N recent traces from the past day
2. Generate text representations and summaries for each trace
3. Store summaries as $ai_trace_summary events in ClickHouse

The summaries will serve as inputs for embedding and clustering workflows.
"""

from datetime import timedelta
from typing import Any

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODE,
    DEFAULT_SAMPLE_SIZE,
    EMIT_EVENTS_TIMEOUT_SECONDS,
    FETCH_HIERARCHY_TIMEOUT_SECONDS,
    GENERATE_SUMMARY_TIMEOUT_SECONDS,
    SAMPLE_TIMEOUT_SECONDS,
    WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_summarization.events import emit_trace_summary_events_activity
from posthog.temporal.llm_analytics.trace_summarization.fetching import fetch_trace_hierarchy_activity
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, TraceSummary
from posthog.temporal.llm_analytics.trace_summarization.sampling import sample_recent_traces_activity
from posthog.temporal.llm_analytics.trace_summarization.summarization import generate_summary_activity

logger = structlog.get_logger(__name__)


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class BatchTraceSummarizationWorkflow(PostHogWorkflow):
    """
    Workflow for batch summarization of traces.

    Runs daily to sample and summarize N recent traces, storing results as
    $ai_trace_summary events for downstream embedding and clustering.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchSummarizationInputs:
        """Parse workflow inputs from string list."""
        return BatchSummarizationInputs(
            team_id=int(inputs[0]),
            sample_size=int(inputs[1]) if len(inputs) > 1 else DEFAULT_SAMPLE_SIZE,
            batch_size=int(inputs[2]) if len(inputs) > 2 else DEFAULT_BATCH_SIZE,
            mode=inputs[3] if len(inputs) > 3 else DEFAULT_MODE,
            start_date=inputs[4] if len(inputs) > 4 else None,
            end_date=inputs[5] if len(inputs) > 5 else None,
        )

    @temporalio.workflow.run
    async def run(self, inputs: BatchSummarizationInputs) -> dict[str, Any]:
        """Execute batch summarization workflow."""
        start_time = temporalio.workflow.now()
        batch_run_id = f"{inputs.team_id}_{start_time.isoformat()}"

        logger.info(
            "Starting batch trace summarization",
            team_id=inputs.team_id,
            sample_size=inputs.sample_size,
            batch_size=inputs.batch_size,
            mode=inputs.mode,
            batch_run_id=batch_run_id,
        )

        # Step 1: Sample traces
        traces = await temporalio.workflow.execute_activity(
            sample_recent_traces_activity,
            inputs,
            schedule_to_close_timeout=timedelta(seconds=SAMPLE_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not traces:
            logger.info("No traces found to summarize", team_id=inputs.team_id)
            return {
                "batch_run_id": batch_run_id,
                "traces_sampled": 0,
                "summaries_generated": 0,
                "events_emitted": 0,
            }

        # Step 2: Process traces in batches
        total_summaries = 0
        total_events = 0

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
                        args=[trace_data, inputs.team_id, inputs.mode],
                        schedule_to_close_timeout=timedelta(seconds=GENERATE_SUMMARY_TIMEOUT_SECONDS),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )

                    batch_summaries.append(summary)

                except Exception as e:
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

                total_summaries += len(batch_summaries)
                total_events += events_count

        end_time = temporalio.workflow.now()
        duration = (end_time - start_time).total_seconds()

        logger.info(
            "Batch trace summarization completed",
            team_id=inputs.team_id,
            batch_run_id=batch_run_id,
            traces_sampled=len(traces),
            summaries_generated=total_summaries,
            events_emitted=total_events,
            duration_seconds=duration,
        )

        return {
            "batch_run_id": batch_run_id,
            "traces_sampled": len(traces),
            "summaries_generated": total_summaries,
            "events_emitted": total_events,
            "duration_seconds": duration,
        }
