"""
Coordinator workflow for batch trace summarization.

This workflow discovers teams with LLM trace activity and spawns
child workflows to process traces for each team.
"""

import dataclasses
from datetime import datetime, timedelta

import structlog
import temporalio

from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.trace_summarization import constants
from posthog.temporal.llm_analytics.trace_summarization.constants import WORKFLOW_EXECUTION_TIMEOUT_MINUTES
from posthog.temporal.llm_analytics.trace_summarization.models import BatchSummarizationInputs, CoordinatorResult
from posthog.temporal.llm_analytics.trace_summarization.workflow import BatchTraceSummarizationWorkflow

logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class BatchTraceSummarizationCoordinatorInputs:
    """Inputs for the coordinator workflow."""

    max_traces: int = 500
    batch_size: int = 10
    mode: str = "detailed"
    window_minutes: int = 60
    model: str | None = None
    lookback_hours: int = 24  # How far back to look for team activity


@dataclasses.dataclass
class TeamsWithTracesResult:
    """Result from querying teams with trace activity."""

    team_ids: list[int]


def query_teams_with_traces(lookback_hours: int, reference_time: datetime | None = None) -> list[int]:
    """
    Query ClickHouse for teams that have LLM trace events in the lookback window.

    Shared logic used by both the coordinator activity and manual trigger script.

    Args:
        lookback_hours: How many hours back to look from reference_time
        reference_time: Reference timestamp to query from (defaults to now() for idempotency in tests)
    """
    from posthog.clickhouse.client import sync_execute

    # Use provided timestamp or default to current time
    if reference_time is None:
        reference_time = datetime.now()

    result = sync_execute(
        """
        SELECT DISTINCT team_id
        FROM events
        WHERE event IN (
            '$ai_trace', '$ai_span', '$ai_generation',
            '$ai_embedding', '$ai_metric', '$ai_feedback'
        )
          AND timestamp >= %(reference_time)s - INTERVAL %(lookback_hours)s HOUR
        ORDER BY team_id
        """,
        {"lookback_hours": lookback_hours, "reference_time": reference_time},
    )
    return [row[0] for row in result]


@temporalio.activity.defn
async def get_teams_with_recent_traces_activity(
    inputs: BatchTraceSummarizationCoordinatorInputs,
    reference_time: datetime,
) -> TeamsWithTracesResult:
    """Query for teams that have LLM trace events in the lookback window.

    Args:
        inputs: Coordinator inputs with lookback configuration
        reference_time: Reference timestamp from workflow for idempotent queries
    """
    from posthog.temporal.llm_analytics.trace_summarization.constants import ALLOWED_TEAM_IDS

    @database_sync_to_async
    def get_teams():
        return query_teams_with_traces(inputs.lookback_hours, reference_time)

    team_ids = await get_teams()

    # Filter by allowlist if configured
    if ALLOWED_TEAM_IDS:
        original_count = len(team_ids)
        team_ids = [team_id for team_id in team_ids if team_id in ALLOWED_TEAM_IDS]
        logger.info(
            "Filtered teams by allowlist",
            original_count=original_count,
            filtered_count=len(team_ids),
            allowed_teams=ALLOWED_TEAM_IDS,
        )
    else:
        logger.info("Found teams with recent trace activity", team_count=len(team_ids))

    return TeamsWithTracesResult(team_ids=team_ids)


@temporalio.workflow.defn(name="batch-trace-summarization-coordinator")
class BatchTraceSummarizationCoordinatorWorkflow(PostHogWorkflow):
    """
    Coordinator workflow that discovers teams with LLM traces and spawns child workflows.

    This runs on a schedule (e.g., hourly) and automatically processes all teams
    with recent trace activity.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> BatchTraceSummarizationCoordinatorInputs:
        """Parse workflow inputs from string list."""
        return BatchTraceSummarizationCoordinatorInputs(
            max_traces=int(inputs[0]) if len(inputs) > 0 else 500,
            batch_size=int(inputs[1]) if len(inputs) > 1 else 10,
            mode=inputs[2] if len(inputs) > 2 else DEFAULT_MODE,
            window_minutes=int(inputs[3]) if len(inputs) > 3 else 60,
            model=inputs[4] if len(inputs) > 4 else None,
            lookback_hours=int(inputs[5]) if len(inputs) > 5 else 24,
        )

    @temporalio.workflow.run
    async def run(self, inputs: BatchTraceSummarizationCoordinatorInputs) -> CoordinatorResult:
        """Execute coordinator workflow."""
        workflow_time = temporalio.workflow.now()

        logger.info(
            "Starting batch trace summarization coordinator",
            max_traces=inputs.max_traces,
            window_minutes=inputs.window_minutes,
            lookback_hours=inputs.lookback_hours,
        )

        # Step 1: Get teams with recent trace activity
        result = await temporalio.workflow.execute_activity(
            get_teams_with_recent_traces_activity,
            args=[inputs, workflow_time],
            schedule_to_close_timeout=timedelta(minutes=5),
            retry_policy=constants.COORDINATOR_ACTIVITY_RETRY_POLICY,
        )

        if not result.team_ids:
            logger.info("No teams with recent trace activity found")
            return CoordinatorResult(
                teams_processed=0,
                teams_failed=0,
                failed_team_ids=[],
                total_traces=0,
                total_summaries=0,
            )

        # Step 2: Spawn child workflows for each team
        total_traces = 0
        total_summaries = 0
        failed_teams = []

        for team_id in result.team_ids:
            try:
                workflow_result = await temporalio.workflow.execute_child_workflow(
                    BatchTraceSummarizationWorkflow.run,
                    BatchSummarizationInputs(
                        team_id=team_id,
                        max_traces=inputs.max_traces,
                        batch_size=inputs.batch_size,
                        mode=inputs.mode,
                        window_minutes=inputs.window_minutes,
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
            teams_processed=len(result.team_ids),
            teams_failed=len(failed_teams),
            failed_team_ids=failed_teams,
            total_traces=total_traces,
            total_summaries=total_summaries,
        )
