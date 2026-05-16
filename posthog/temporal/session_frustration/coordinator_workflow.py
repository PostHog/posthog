"""Coordinator workflow for session frustration detection.

Runs on an hourly schedule, discovers teams with frustration detection enabled,
and fans out per-team child workflows in batches.
"""

import json
from datetime import timedelta
from typing import Any

import structlog
import temporalio
import posthoganalytics
import temporalio.exceptions
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_frustration.constants import MAX_CONCURRENT_TEAMS
from posthog.temporal.session_frustration.team_workflow import SessionFrustrationTeamWorkflow
from posthog.temporal.session_frustration.types import CoordinatorInputs, TeamWorkflowInputs, TeamWorkflowResult

logger = structlog.get_logger(__name__)


@temporalio.workflow.defn(name="session-frustration-detection-coordinator")
class SessionFrustrationCoordinatorWorkflow(PostHogWorkflow):
    """Hourly coordinator that fans out frustration detection per team."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CoordinatorInputs:
        loaded = json.loads(inputs[0])
        return CoordinatorInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: CoordinatorInputs) -> dict[str, Any]:
        from posthog.temporal.session_frustration.activities import get_opted_in_team_ids_activity

        enabled_teams: list[tuple[int, str]] = await workflow.execute_activity(
            get_opted_in_team_ids_activity,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
            ),
        )

        if not enabled_teams:
            workflow.logger.debug("No teams with frustration detection enabled")
            return {
                "teams_processed": 0,
                "teams_succeeded": 0,
                "teams_failed": 0,
                "total_events_emitted": 0,
            }

        workflow.logger.debug(f"Processing {len(enabled_teams)} teams with frustration detection enabled")

        total_events_emitted = 0
        failed_teams: set[int] = set()
        successful_teams: set[int] = set()

        for batch_start in range(0, len(enabled_teams), MAX_CONCURRENT_TEAMS):
            batch = enabled_teams[batch_start : batch_start + MAX_CONCURRENT_TEAMS]

            workflow_handles: dict[int, Any] = {}
            for team_id, api_token in batch:
                try:
                    handle = await workflow.start_child_workflow(
                        SessionFrustrationTeamWorkflow.run,
                        TeamWorkflowInputs(
                            team_id=team_id,
                            api_token=api_token,
                            lookback_hours=inputs.lookback_hours,
                        ),
                        id=f"session-frustration-team-{team_id}",
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        execution_timeout=timedelta(minutes=10),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=10),
                            maximum_interval=timedelta(minutes=2),
                            backoff_coefficient=2.0,
                        ),
                        parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
                    )
                    workflow_handles[team_id] = handle
                except temporalio.exceptions.WorkflowAlreadyStartedError:
                    continue
                except Exception:
                    workflow.logger.exception(f"Failed to start frustration detection for team {team_id}")
                    posthoganalytics.capture_exception(properties={"team_id": team_id})
                    failed_teams.add(team_id)

            for team_id, handle in workflow_handles.items():
                try:
                    result: TeamWorkflowResult = await handle
                    total_events_emitted += result.events_emitted
                    successful_teams.add(team_id)
                except Exception:
                    workflow.logger.exception(f"Frustration detection errored for team {team_id}")
                    posthoganalytics.capture_exception(properties={"team_id": team_id})
                    failed_teams.add(team_id)

        return {
            "teams_processed": len(enabled_teams),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": list(failed_teams),
            "total_events_emitted": total_events_emitted,
        }
