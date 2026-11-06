"""Weekly coordinator and per-team workflow. Activities pass ids and counts, never trace content."""

import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.models.team import Team
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.utils import on_asyncify_pool

    from .client import COORDINATOR_WORKFLOW_NAME, TEAM_TIMEOUT, TEAM_WORKFLOW_NAME, CoordinatorInputs, TeamRunInputs
    from .config import load_settings
    from .eligibility import eligible_team_ids
    from .pipeline import create_run, execute_run

RUN_ATTEMPT_TIMEOUT = timedelta(minutes=15)


@frozen
class CoordinatorPlan:
    team_ids: list[int]
    max_concurrent_teams: int


@frozen
class ExecuteRunInputs:
    run_id: str
    include_paid: bool


@activity.defn(name="llma-eval-suggestions-plan")
async def plan_eval_suggestions_activity() -> CoordinatorPlan:
    async with Heartbeater():
        suggestion_settings = await on_asyncify_pool(load_settings)()
        team_ids = await on_asyncify_pool(eligible_team_ids)(suggestion_settings)
    return CoordinatorPlan(team_ids=team_ids, max_concurrent_teams=suggestion_settings.max_concurrent_teams)


def _start_run(inputs: TeamRunInputs) -> str:
    team = Team.objects.get(id=inputs.team_id)
    return str(create_run(team, inputs.trigger, inputs.batch_id).id)


@activity.defn(name="llma-eval-suggestions-start-run")
async def start_eval_suggestions_run_activity(inputs: TeamRunInputs) -> str:
    return await on_asyncify_pool(_start_run)(inputs)


@activity.defn(name="llma-eval-suggestions-execute-run")
async def execute_eval_suggestions_run_activity(inputs: ExecuteRunInputs) -> int:
    async with Heartbeater():
        suggestion_settings = await on_asyncify_pool(load_settings)()
        return await on_asyncify_pool(execute_run)(
            inputs.run_id, include_paid=inputs.include_paid, settings=suggestion_settings
        )


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class EvalSuggestionsTeamWorkflow(PostHogWorkflow):
    inputs_cls = TeamRunInputs

    @workflow.run
    async def run(self, inputs: TeamRunInputs) -> int:
        run_id = await workflow.execute_activity(
            start_eval_suggestions_run_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return await workflow.execute_activity(
            execute_eval_suggestions_run_activity,
            ExecuteRunInputs(run_id=run_id, include_paid=inputs.include_paid),
            start_to_close_timeout=RUN_ATTEMPT_TIMEOUT,
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
        )


@workflow.defn(name=COORDINATOR_WORKFLOW_NAME)
class EvalSuggestionsCoordinatorWorkflow(PostHogWorkflow):
    inputs_cls = CoordinatorInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: CoordinatorInputs) -> dict[str, int]:
        if inputs.remaining_team_ids is None:
            plan = await workflow.execute_activity(
                plan_eval_suggestions_activity,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            team_ids, concurrency = plan.team_ids, plan.max_concurrent_teams
            batch_id = workflow.info().workflow_id
        else:
            team_ids, concurrency, batch_id = inputs.remaining_team_ids, inputs.max_concurrent_teams, inputs.batch_id

        succeeded = failed = 0
        for start in range(0, len(team_ids), concurrency):
            batch = team_ids[start : start + concurrency]
            handles = [
                await workflow.start_child_workflow(
                    EvalSuggestionsTeamWorkflow.run,
                    TeamRunInputs(team_id=team_id, trigger="scheduled", include_paid=True, batch_id=batch_id),
                    id=f"{TEAM_WORKFLOW_NAME}-{team_id}-{batch_id}",
                    execution_timeout=TEAM_TIMEOUT,
                    parent_close_policy=workflow.ParentClosePolicy.TERMINATE,
                )
                for team_id in batch
            ]
            for outcome in await asyncio.gather(*handles, return_exceptions=True):
                if isinstance(outcome, BaseException):
                    failed += 1
                else:
                    succeeded += 1
            remaining = team_ids[start + concurrency :]
            if remaining and workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    CoordinatorInputs(remaining_team_ids=remaining, batch_id=batch_id, max_concurrent_teams=concurrency)
                )
        return {"teams_succeeded": succeeded, "teams_failed": failed}


WORKFLOWS = [EvalSuggestionsCoordinatorWorkflow, EvalSuggestionsTeamWorkflow]
ACTIVITIES = [
    plan_eval_suggestions_activity,
    start_eval_suggestions_run_activity,
    execute_eval_suggestions_run_activity,
]
