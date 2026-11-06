"""Weekly coordinator and per-team workflow. Activities pass ids and counts, never trace content."""

import time
import uuid
import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.models.team import Team
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.utils import on_asyncify_pool

    from .client import COORDINATOR_WORKFLOW_NAME, TEAM_TIMEOUT, TEAM_WORKFLOW_NAME, CoordinatorInputs, TeamRunInputs
    from .config import load_settings
    from .eligibility import eligible_team_ids
    from .pipeline import create_run, execute_run, fail_run

RUN_ATTEMPT_TIMEOUT = timedelta(minutes=15)


@frozen
class CoordinatorPlan:
    team_ids: list[int]
    max_concurrent_teams: int


@frozen
class ExecuteRunInputs:
    team_id: int
    run_id: str
    include_paid: bool


@frozen
class StartRunInputs:
    run: TeamRunInputs
    # Derived from the workflow run, so a retried start finds the run an earlier attempt created.
    run_id: str


@frozen
class FailRunInputs:
    team_id: int
    run_id: str
    error: str


@activity.defn(name="llma-eval-suggestions-plan")
async def plan_eval_suggestions_activity() -> CoordinatorPlan:
    async with Heartbeater():
        suggestion_settings = await on_asyncify_pool(load_settings)()
        team_ids = await on_asyncify_pool(eligible_team_ids)(suggestion_settings)
    return CoordinatorPlan(team_ids=team_ids, max_concurrent_teams=suggestion_settings.max_concurrent_teams)


def _start_run(inputs: StartRunInputs) -> str:
    team = Team.objects.get(id=inputs.run.team_id)
    return str(create_run(team, inputs.run.trigger, inputs.run.batch_id, run_id=inputs.run_id).id)


@activity.defn(name="llma-eval-suggestions-start-run")
async def start_eval_suggestions_run_activity(inputs: StartRunInputs) -> str:
    return await on_asyncify_pool(_start_run)(inputs)


@activity.defn(name="llma-eval-suggestions-fail-run")
async def fail_eval_suggestions_run_activity(inputs: FailRunInputs) -> None:
    await on_asyncify_pool(fail_run)(inputs.team_id, inputs.run_id, inputs.error)


@activity.defn(name="llma-eval-suggestions-execute-run")
async def execute_eval_suggestions_run_activity(inputs: ExecuteRunInputs) -> int:
    async with Heartbeater():
        suggestion_settings = await on_asyncify_pool(load_settings)()
        # A minute short of the attempt's timeout, so the run stops itself before Temporal starts a retry.
        deadline = time.monotonic() + RUN_ATTEMPT_TIMEOUT.total_seconds() - 60
        return await on_asyncify_pool(execute_run)(
            inputs.team_id,
            inputs.run_id,
            include_paid=inputs.include_paid,
            settings=suggestion_settings,
            deadline=deadline,
        )


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class EvalSuggestionsTeamWorkflow(PostHogWorkflow):
    inputs_cls = TeamRunInputs

    @workflow.run
    async def run(self, inputs: TeamRunInputs) -> int:
        info = workflow.info()
        # Known before the start activity runs, so a start that created the row and then failed is cleaned up too.
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{info.workflow_id}/{info.run_id}"))
        try:
            await workflow.execute_activity(
                start_eval_suggestions_run_activity,
                StartRunInputs(run=inputs, run_id=run_id),
                start_to_close_timeout=timedelta(minutes=1),
                # Each activity has a schedule-to-close deadline, so worker queue time cannot outlast the workflow.
                schedule_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return await workflow.execute_activity(
                execute_eval_suggestions_run_activity,
                ExecuteRunInputs(team_id=inputs.team_id, run_id=run_id, include_paid=inputs.include_paid),
                start_to_close_timeout=RUN_ATTEMPT_TIMEOUT,
                schedule_to_close_timeout=RUN_ATTEMPT_TIMEOUT * 2 + timedelta(minutes=8),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
            )
        except ActivityError as error:
            # A worker that died or timed out never reached execute_run's own failure handling.
            await workflow.execute_activity(
                fail_eval_suggestions_run_activity,
                FailRunInputs(team_id=inputs.team_id, run_id=run_id, error=str(error.cause or error)),
                start_to_close_timeout=timedelta(minutes=1),
                schedule_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise


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
        queue = list(team_ids)
        running: set[asyncio.Future[int]] = set()
        # A slot refills as soon as one team finishes, so a slow team holds one slot, not the whole batch.
        while queue or running:
            while queue and len(running) < concurrency and not workflow.info().is_continue_as_new_suggested():
                team_id = queue.pop(0)
                running.add(
                    await workflow.start_child_workflow(
                        EvalSuggestionsTeamWorkflow.run,
                        TeamRunInputs(team_id=team_id, trigger="scheduled", include_paid=True, batch_id=batch_id),
                        id=f"{TEAM_WORKFLOW_NAME}-{team_id}-{batch_id}",
                        execution_timeout=TEAM_TIMEOUT,
                        parent_close_policy=workflow.ParentClosePolicy.TERMINATE,
                    )
                )
            if not running:
                break
            done, pending = await workflow.wait(running, return_when=asyncio.FIRST_COMPLETED)
            running = set(pending)
            for handle in done:
                if handle.exception() is None:
                    succeeded += 1
                else:
                    failed += 1
        if queue:
            # History grew too long. Children end with their parent, so the rest start in a fresh run once all
            # running ones finished.
            workflow.continue_as_new(
                CoordinatorInputs(remaining_team_ids=queue, batch_id=batch_id, max_concurrent_teams=concurrency)
            )
        return {"teams_succeeded": succeeded, "teams_failed": failed}


WORKFLOWS = [EvalSuggestionsCoordinatorWorkflow, EvalSuggestionsTeamWorkflow]
ACTIVITIES = [
    plan_eval_suggestions_activity,
    start_eval_suggestions_run_activity,
    execute_eval_suggestions_run_activity,
    fail_eval_suggestions_run_activity,
]
