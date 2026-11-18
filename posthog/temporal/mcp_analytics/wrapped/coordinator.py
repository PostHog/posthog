"""Compute MCP Wrapped for chosen projects, or every project with tool calls this year, a few at a time.

Nothing schedules this workflow. Someone starts it when the year's wrap should be filled:

    python manage.py execute_temporal_workflow mcpa-wrapped-coordinator <year> [<team_id> ...] \
        --task-queue <MCPA_TASK_QUEUE>

One project's failure is recorded and the run moves on, so a slow or broken project never blocks the rest.
"""

import asyncio
import dataclasses
from collections import Counter
from typing import Any

import temporalio
import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.mcp_analytics.wrapped.constants import (
    COORDINATOR_WORKFLOW_NAME,
    DISCOVERY_ACTIVITY_TIMEOUT,
    DISCOVERY_RETRY_POLICY,
    GENERATE_ACTIVITY_TIMEOUT,
    GENERATE_HEARTBEAT_TIMEOUT,
    GENERATE_RETRY_POLICY,
    MAX_CONCURRENT_TEAMS,
)

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.mcp_analytics.wrapped.activities import (
        WrappedDiscoveryInputs,
        WrappedTeamInputs,
        discover_wrapped_team_ids_activity,
        generate_wrapped_activity,
    )


@dataclasses.dataclass(frozen=True)
class WrappedCoordinatorInputs:
    # None covers the year the run starts in.
    year: int | None = None
    # None discovers every project with tool calls in the year.
    team_ids: list[int] | None = None
    max_concurrent_teams: int = MAX_CONCURRENT_TEAMS


@temporalio.workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class MCPWrappedCoordinatorWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> WrappedCoordinatorInputs:
        return WrappedCoordinatorInputs(
            year=int(inputs[0]) if inputs else None,
            team_ids=[int(team_id) for team_id in inputs[1:]] or None,
        )

    @temporalio.workflow.run
    async def run(self, inputs: WrappedCoordinatorInputs) -> dict[str, Any]:
        year = inputs.year or temporalio.workflow.now().year
        team_ids = inputs.team_ids
        if team_ids is None:
            team_ids = await temporalio.workflow.execute_activity(
                discover_wrapped_team_ids_activity,
                WrappedDiscoveryInputs(year=year),
                start_to_close_timeout=DISCOVERY_ACTIVITY_TIMEOUT,
                retry_policy=DISCOVERY_RETRY_POLICY,
            )

        statuses: Counter[str] = Counter()
        failed_team_ids: list[int] = []
        for start in range(0, len(team_ids), inputs.max_concurrent_teams):
            batch = team_ids[start : start + inputs.max_concurrent_teams]
            results = await asyncio.gather(
                *(
                    temporalio.workflow.execute_activity(
                        generate_wrapped_activity,
                        WrappedTeamInputs(team_id=team_id, year=year),
                        start_to_close_timeout=GENERATE_ACTIVITY_TIMEOUT,
                        heartbeat_timeout=GENERATE_HEARTBEAT_TIMEOUT,
                        retry_policy=GENERATE_RETRY_POLICY,
                    )
                    for team_id in batch
                ),
                return_exceptions=True,
            )
            for team_id, result in zip(batch, results):
                if isinstance(result, BaseException):
                    temporalio.workflow.logger.warning("mcpa.wrapped.team_failed", extra={"team_id": team_id})
                    failed_team_ids.append(team_id)
                else:
                    statuses[result] += 1

        return {
            "year": year,
            "teams": len(team_ids),
            "statuses": dict(statuses),
            "failed_team_ids": failed_team_ids,
        }
