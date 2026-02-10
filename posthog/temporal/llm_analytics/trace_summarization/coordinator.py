"""
Coordinator workflow for batch trace summarization.

This workflow discovers teams dynamically via the team discovery activity
and spawns child workflows to process traces for each team.

Per-team child workflows handle the case where a team has no traces
gracefully (returning empty results).

Teams are processed in parallel batches (default 3 at a time) using
start_child_workflow + await pattern for controlled concurrency.
"""

import dataclasses
from datetime import timedelta

import structlog
import temporalio
from temporalio.workflow import ChildWorkflowHandle

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    CHILD_WORKFLOW_ID_PREFIX,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_CONCURRENT_TEAMS,
    DEFAULT_MAX_ITEMS_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_WINDOW_MINUTES,
    GENERATION_CHILD_WORKFLOW_ID_PREFIX,
    WORKFLOW_EXECUTION_TIMEOUT_MINUTES,
)
from posthog.temporal.llm_analytics.trace_summarization.models import (
    AnalysisLevel,
    BatchSummarizationInputs,
    BatchSummarizationResult,
    CoordinatorResult,
)
from posthog.temporal.llm_analytics.trace_summarization.workflow import BatchTraceSummarizationWorkflow

from products.llm_analytics.backend.summarization.models import SummarizationMode

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.llm_analytics.team_discovery import (
        DISCOVERY_ACTIVITY_RETRY_POLICY,
        DISCOVERY_ACTIVITY_TIMEOUT,
        GUARANTEED_TEAM_IDS,
        SAMPLE_PERCENTAGE,
        TeamDiscoveryInput,
        get_team_ids_for_llm_analytics,
    )

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class BatchTraceSummarizationCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    analysis_level: AnalysisLevel = "trace"  # "trace" or "generation"
    max_items: int = DEFAULT_MAX_ITEMS_PER_WINDOW
    batch_size: int = DEFAULT_BATCH_SIZE
    mode: SummarizationMode = DEFAULT_MODE
    window_minutes: int = DEFAULT_WINDOW_MINUTES
    model: str = DEFAULT_MODEL
    max_concurrent_teams: int = DEFAULT_MAX_CONCURRENT_TEAMS


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class BatchTraceSummarizationCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow that discovers teams dynamically and spawns child
    workflows for each team. Teams with no traces will complete quickly
    with empty results.

    Teams are processed in parallel batches for controlled concurrency,
    using start_child_workflow + await to start all workflows in a batch
    before waiting for results.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchTraceSummarizationCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return BatchTraceSummarizationCoordinatorInputs(
            analysis_level="generation" if len(inputs) > 0 and inputs[0] == "generation" else "trace",
            max_items=int(inputs[1]) if len(inputs) > 1 else DEFAULT_MAX_ITEMS_PER_WINDOW,
            batch_size=int(inputs[2]) if len(inputs) > 2 else DEFAULT_BATCH_SIZE,
            mode=SummarizationMode(inputs[3]) if len(inputs) > 3 else DEFAULT_MODE,
            window_minutes=int(inputs[4]) if len(inputs) > 4 else DEFAULT_WINDOW_MINUTES,
            model=inputs[5] if len(inputs) > 5 else DEFAULT_MODEL,
        )

    @temporalio.workflow.run
    async def run(self, inputs: BatchTraceSummarizationCoordinatorInputs) -> CoordinatorResult:
        """Execute coordinator workflow."""
        logger.info(
            "Starting batch trace summarization coordinator",
            analysis_level=inputs.analysis_level,
            max_items=inputs.max_items,
            window_minutes=inputs.window_minutes,
        )

        # Discover teams dynamically via activity, falling back to guaranteed
        # teams if the activity fails (e.g. ClickHouse timeout).
        try:
            team_ids = await temporalio.workflow.execute_activity(
                get_team_ids_for_llm_analytics,
                TeamDiscoveryInput(sample_percentage=SAMPLE_PERCENTAGE),
                start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
                retry_policy=DISCOVERY_ACTIVITY_RETRY_POLICY,
            )
        except Exception:
            logger.warning("Team discovery activity failed, falling back to guaranteed teams", exc_info=True)
            team_ids = sorted(GUARANTEED_TEAM_IDS)

        logger.info("Processing discovered teams", team_count=len(team_ids), team_ids=team_ids)

        # Spawn child workflows for each team with concurrency limit.
        # Uses start_child_workflow + await pattern: start all workflows in a
        # batch first, then await results. This runs teams in parallel within
        # each batch instead of sequentially.
        total_items = 0
        total_summaries = 0
        failed_teams: list[int] = []
        successful_teams: list[int] = []
        child_id_prefix = (
            GENERATION_CHILD_WORKFLOW_ID_PREFIX if inputs.analysis_level == "generation" else CHILD_WORKFLOW_ID_PREFIX
        )

        max_concurrent = inputs.max_concurrent_teams
        for batch_start in range(0, len(team_ids), max_concurrent):
            batch = team_ids[batch_start : batch_start + max_concurrent]

            # Start all workflows in batch concurrently
            workflow_handles: list[
                tuple[int, ChildWorkflowHandle[BatchTraceSummarizationWorkflow, BatchSummarizationResult]]
            ] = []
            for team_id in batch:
                handle = await temporalio.workflow.start_child_workflow(
                    BatchTraceSummarizationWorkflow.run,
                    BatchSummarizationInputs(
                        team_id=team_id,
                        analysis_level=inputs.analysis_level,
                        max_items=inputs.max_items,
                        batch_size=inputs.batch_size,
                        mode=inputs.mode,
                        window_minutes=inputs.window_minutes,
                        model=inputs.model,
                    ),
                    id=f"{child_id_prefix}-{team_id}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=timedelta(minutes=WORKFLOW_EXECUTION_TIMEOUT_MINUTES),
                    retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.TERMINATE,
                )
                workflow_handles.append((team_id, handle))

            # Wait for all workflows in batch to complete
            for team_id, handle in workflow_handles:
                try:
                    workflow_result: BatchSummarizationResult = await handle
                    total_items += workflow_result.metrics.items_queried
                    total_summaries += workflow_result.metrics.summaries_generated
                    successful_teams.append(team_id)

                except Exception:
                    logger.exception("Failed to process team", team_id=team_id)
                    failed_teams.append(team_id)

        logger.info(
            "Batch trace summarization coordinator completed",
            teams_processed=len(team_ids),
            teams_succeeded=len(successful_teams),
            teams_failed=len(failed_teams),
            total_items=total_items,
            total_summaries=total_summaries,
        )

        return CoordinatorResult(
            teams_processed=len(team_ids),
            teams_failed=len(failed_teams),
            failed_team_ids=failed_teams,
            total_items=total_items,
            total_summaries=total_summaries,
        )
