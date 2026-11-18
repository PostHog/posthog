import uuid
from datetime import UTC, datetime
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.mcp_analytics.wrapped.activities import WrappedDiscoveryInputs, WrappedTeamInputs
from posthog.temporal.mcp_analytics.wrapped.coordinator import MCPWrappedCoordinatorWorkflow, WrappedCoordinatorInputs

FAILING_TEAM_ID = 3
_discovered_years: list[int] = []


@activity.defn(name="discover_wrapped_team_ids_activity")
async def stub_discovery(inputs: WrappedDiscoveryInputs) -> list[int]:
    _discovered_years.append(inputs.year)
    return [1, 2, 3, 4, 5]


@activity.defn(name="generate_wrapped_activity")
async def stub_generate(inputs: WrappedTeamInputs) -> str:
    if inputs.team_id == FAILING_TEAM_ID:
        raise ApplicationError("ClickHouse went away", non_retryable=True)
    return "ready" if inputs.team_id % 2 else "ineligible"


async def _run(inputs: WrappedCoordinatorInputs) -> dict[str, Any]:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[MCPWrappedCoordinatorWorkflow],
            activities=[stub_discovery, stub_generate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                MCPWrappedCoordinatorWorkflow.run, inputs, id=str(uuid.uuid4()), task_queue=task_queue
            )


async def test_one_failed_project_does_not_stop_the_others() -> None:
    result = await _run(WrappedCoordinatorInputs(year=2026, max_concurrent_teams=2))

    assert result == {
        "year": 2026,
        "teams": 5,
        "statuses": {"ready": 2, "ineligible": 2},
        "failed_team_ids": [FAILING_TEAM_ID],
    }


async def test_the_schedule_covers_the_year_it_fires_in() -> None:
    _discovered_years.clear()

    result = await _run(WrappedCoordinatorInputs())

    assert _discovered_years == [result["year"]] == [datetime.now(UTC).year]
