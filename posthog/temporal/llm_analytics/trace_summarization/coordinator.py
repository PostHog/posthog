"""
Coordinator workflow for batch trace summarization.

This workflow processes traces for teams in the ALLOWED_TEAM_IDS list
and spawns child workflows to process traces for each team.

Team discovery uses a simple allowlist approach to avoid cross-team
ClickHouse queries. The per-team child workflows handle the case where
a team has no traces gracefully (returning empty results).
"""

import dataclasses
from datetime import timedelta

import structlog
import temporalio

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    ALLOWED_TEAM_IDS,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_WINDOW_MINUTES,
    WORKFLOW_EXECUTION_TIMEOUT_MINUTES,
)
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, CoordinatorResult
from posthog.temporal.llm_analytics.trace_summarization.workflow import BatchTraceSummarizationWorkflow

from products.llm_analytics.backend.summarization.models import SummarizationMode, SummarizationProvider

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class BatchTraceSummarizationCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    max_traces: int = DEFAULT_MAX_TRACES_PER_WINDOW
    batch_size: int = DEFAULT_BATCH_SIZE
    mode: SummarizationMode = DEFAULT_MODE
    window_minutes: int = DEFAULT_WINDOW_MINUTES
    provider: SummarizationProvider = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL


def get_allowed_team_ids() -> list[int]:
    """
    Get the list of team IDs that should be processed for trace summarization.

    Uses a simple allowlist approach to avoid cross-team ClickHouse queries.
    Per-team child workflows handle the case where a team has no traces gracefully.

    Returns:
        List of team IDs from ALLOWED_TEAM_IDS constant
    """
    return ALLOWED_TEAM_IDS.copy()


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class BatchTraceSummarizationCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow that processes traces for teams in ALLOWED_TEAM_IDS.

    This runs on a schedule (e.g., hourly) and spawns child workflows for each
    team in the allowlist. Teams with no traces will complete quickly with
    empty results.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchTraceSummarizationCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return BatchTraceSummarizationCoordinatorInputs(
            max_traces=int(inputs[0]) if len(inputs) > 0 else DEFAULT_MAX_TRACES_PER_WINDOW,
            batch_size=int(inputs[1]) if len(inputs) > 1 else DEFAULT_BATCH_SIZE,
            mode=SummarizationMode(inputs[2]) if len(inputs) > 2 else DEFAULT_MODE,
            window_minutes=int(inputs[3]) if len(inputs) > 3 else DEFAULT_WINDOW_MINUTES,
            provider=SummarizationProvider(inputs[4]) if len(inputs) > 4 else DEFAULT_PROVIDER,
            model=inputs[5] if len(inputs) > 5 else DEFAULT_MODEL,
        )

    @temporalio.workflow.run
    async def run(self, inputs: BatchTraceSummarizationCoordinatorInputs) -> CoordinatorResult:
        """Execute coordinator workflow."""
        logger.info(
            "Starting batch trace summarization coordinator",
            max_traces=inputs.max_traces,
            window_minutes=inputs.window_minutes,
        )

        # Get teams from allowlist (no cross-team ClickHouse query needed)
        team_ids = get_allowed_team_ids()

        if not team_ids:
            logger.info("No teams in allowlist")
            return CoordinatorResult(
                teams_processed=0,
                teams_failed=0,
                failed_team_ids=[],
                total_traces=0,
                total_summaries=0,
            )

        logger.info("Processing teams from allowlist", team_count=len(team_ids), team_ids=team_ids)

        # Spawn child workflows for each team
        total_traces = 0
        total_summaries = 0
        failed_teams = []

        for team_id in team_ids:
            try:
                workflow_result = await temporalio.workflow.execute_child_workflow(
                    BatchTraceSummarizationWorkflow.run,
                    BatchSummarizationInputs(
                        team_id=team_id,
                        max_traces=inputs.max_traces,
                        batch_size=inputs.batch_size,
                        mode=inputs.mode,
                        window_minutes=inputs.window_minutes,
                        provider=inputs.provider,
                        model=inputs.model,
                    ),
                    id=f"batch-summarization-team-{team_id}-{temporalio.workflow.now().isoformat()}",
                    execution_timeout=timedelta(minutes=WORKFLOW_EXECUTION_TIMEOUT_MINUTES),
                    retry_policy=constants.COORDINATOR_CHILD_WORKFLOW_RETRY_POLICY,
                )

                total_traces += workflow_result.metrics.traces_queried
                total_summaries += workflow_result.metrics.summaries_generated

            except Exception as e:
                logger.exception("Failed to process team", team_id=team_id, error=str(e))
                failed_teams.append(team_id)
                # Continue with other teams

        return CoordinatorResult(
            teams_processed=len(team_ids),
            teams_failed=len(failed_teams),
            failed_team_ids=failed_teams,
            total_traces=total_traces,
            total_summaries=total_summaries,
        )
