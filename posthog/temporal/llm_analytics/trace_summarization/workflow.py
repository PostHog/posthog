"""
Batch trace summarization workflow for LLMA.

This workflow runs on a schedule (e.g., hourly) to:
1. Query recent traces from a time window
2. Generate text representations and summaries for each trace
3. Store summaries as $ai_trace_summary events in ClickHouse
4. Queue embeddings for summaries via Kafka for async processing

The summaries and embeddings serve as inputs for clustering and semantic search.
"""

import asyncio
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any

import structlog
import temporalio

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_ITEMS_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_WINDOW_MINUTES,
    GENERATE_SUMMARY_TIMEOUT_SECONDS,
    MAX_LENGTH_BY_PROVIDER,
    SAMPLE_TIMEOUT_SECONDS,
    WORKFLOW_NAME,
)
from posthog.temporal.llm_analytics.trace_summarization.generation_summarization import (
    generate_and_save_generation_summary_activity,
)
from posthog.temporal.llm_analytics.trace_summarization.models import (
    BatchSummarizationInputs,
    BatchSummarizationMetrics,
    BatchSummarizationResult,
    SampledItem,
    SummarizationActivityResult,
)
from posthog.temporal.llm_analytics.trace_summarization.sampling import sample_items_in_window_activity
from posthog.temporal.llm_analytics.trace_summarization.summarization import generate_and_save_summary_activity

from products.llm_analytics.backend.summarization.models import SummarizationMode, SummarizationProvider

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
            analysis_level="generation" if len(inputs) > 1 and inputs[1] == "generation" else "trace",
            max_items=int(inputs[2]) if len(inputs) > 2 else DEFAULT_MAX_ITEMS_PER_WINDOW,
            batch_size=int(inputs[3]) if len(inputs) > 3 else DEFAULT_BATCH_SIZE,
            mode=SummarizationMode(inputs[4]) if len(inputs) > 4 else DEFAULT_MODE,
            window_minutes=int(inputs[5]) if len(inputs) > 5 else DEFAULT_WINDOW_MINUTES,
            window_start=inputs[6] if len(inputs) > 6 else None,
            window_end=inputs[7] if len(inputs) > 7 else None,
            provider=SummarizationProvider(inputs[8]) if len(inputs) > 8 else DEFAULT_PROVIDER,
            model=inputs[9] if len(inputs) > 9 else DEFAULT_MODEL,
        )

    @staticmethod
    async def _process_item(
        semaphore: asyncio.Semaphore,
        item: SampledItem,
        team_id: int,
        window_start: str,
        window_end: str,
        mode: str,
        batch_run_id: str,
        provider: str | None,
        model: str | None,
        max_length: int | None,
    ) -> SummarizationActivityResult:
        """Process a single trace or generation with semaphore-controlled concurrency."""
        async with semaphore:
            if item.generation_id:
                # Generation-level
                return await temporalio.workflow.execute_activity(
                    generate_and_save_generation_summary_activity,
                    args=[
                        item.generation_id,
                        item.trace_id,
                        item.trace_first_timestamp,
                        team_id,
                        window_start,
                        window_end,
                        mode,
                        batch_run_id,
                        provider,
                        model,
                        max_length,
                    ],
                    activity_id=f"summarize-gen-{item.generation_id}",
                    schedule_to_close_timeout=timedelta(seconds=GENERATE_SUMMARY_TIMEOUT_SECONDS),
                    retry_policy=constants.SUMMARIZE_RETRY_POLICY,
                )
            else:
                # Trace-level
                return await temporalio.workflow.execute_activity(
                    generate_and_save_summary_activity,
                    args=[
                        item.trace_id,
                        item.trace_first_timestamp,
                        team_id,
                        window_start,
                        window_end,
                        mode,
                        batch_run_id,
                        provider,
                        model,
                        max_length,
                    ],
                    activity_id=f"summarize-{item.trace_id}",
                    schedule_to_close_timeout=timedelta(seconds=GENERATE_SUMMARY_TIMEOUT_SECONDS),
                    retry_policy=constants.SUMMARIZE_RETRY_POLICY,
                )

    @temporalio.workflow.run
    async def run(self, inputs: BatchSummarizationInputs) -> BatchSummarizationResult:
        """
        Execute batch summarization workflow.

        Args:
            inputs: BatchSummarizationInputs containing workflow parameters

        Returns:
            BatchSummarizationResult containing metrics and results
        """
        start_time = temporalio.workflow.now()
        batch_run_id = f"{inputs.team_id}_{start_time.isoformat()}"
        metrics = BatchSummarizationMetrics()

        # Compute window dates for queries using workflow time for determinism
        # This ensures consistent windows even if activities are delayed
        if inputs.window_start and inputs.window_end:
            window_start = inputs.window_start
            window_end = inputs.window_end
        else:
            now = temporalio.workflow.now()
            window_end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            window_start = (now - timedelta(minutes=inputs.window_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Prepare inputs with computed window
        inputs_with_window = BatchSummarizationInputs(
            team_id=inputs.team_id,
            analysis_level=inputs.analysis_level,
            max_items=inputs.max_items,
            batch_size=inputs.batch_size,
            mode=inputs.mode,
            window_minutes=inputs.window_minutes,
            provider=inputs.provider,
            model=inputs.model,
            window_start=window_start,
            window_end=window_end,
        )

        # Look up max_length based on provider for context window safety
        max_length = MAX_LENGTH_BY_PROVIDER.get(inputs.provider)
        semaphore = asyncio.Semaphore(inputs.batch_size)

        # Sample items (traces or generations) using unified sampling
        items = await temporalio.workflow.execute_activity(
            sample_items_in_window_activity,
            inputs_with_window,
            schedule_to_close_timeout=timedelta(seconds=SAMPLE_TIMEOUT_SECONDS),
            retry_policy=constants.SAMPLE_RETRY_POLICY,
        )
        metrics.items_queried = len(items)

        # Process all items
        tasks: list[Coroutine[Any, Any, SummarizationActivityResult]] = [
            self._process_item(
                semaphore=semaphore,
                item=item,
                team_id=inputs.team_id,
                window_start=window_start,
                window_end=window_end,
                mode=inputs.mode,
                batch_run_id=batch_run_id,
                provider=inputs.provider,
                model=inputs.model,
                max_length=max_length,
            )
            for item in items
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Track results
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                item = items[i]
                logger.exception(
                    "Activity failed",
                    trace_id=item.trace_id,
                    generation_id=item.generation_id,
                    error=str(result),
                )
                metrics.summaries_failed += 1
            elif result.success:
                metrics.summaries_generated += 1
                if result.embedding_requested:
                    metrics.embedding_requests_succeeded += 1
                else:
                    metrics.embedding_requests_failed += 1
            elif result.skipped:
                metrics.summaries_skipped += 1
            else:
                metrics.summaries_failed += 1

        end_time = temporalio.workflow.now()
        metrics.duration_seconds = (end_time - start_time).total_seconds()

        return BatchSummarizationResult(
            batch_run_id=batch_run_id,
            metrics=metrics,
        )
