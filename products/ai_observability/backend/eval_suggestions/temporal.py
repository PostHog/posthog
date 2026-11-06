"""Weekly coordinator and per-team workflow. Activities pass ids and counts, never trace content.

A team's run is one activity per stage, so a retry redoes only the stage that failed and a timeout stops only that
stage. Screening and drafting are paid and optional: when either fails, the run publishes without it.
"""

import time
import uuid
import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.models.team import Team
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.utils import on_asyncify_pool

    from .client import (
        COORDINATOR_WORKFLOW_NAME,
        DRAFT,
        FAIL_RUN,
        MEASURE,
        PUBLISH,
        SCREEN,
        START_RUN,
        TEAM_TIMEOUT,
        TEAM_WORKFLOW_NAME,
        ActivityLimits,
        CoordinatorInputs,
        TeamRunInputs,
    )
    from .config import load_settings
    from .eligibility import eligible_team_ids
    from .pipeline import create_run, draft_stage, fail_run, measure_stage, publish_stage, screen_stage

# Each stage stops itself this long before Temporal times its attempt out.
DEADLINE_MARGIN = timedelta(minutes=1)


@frozen
class CoordinatorPlan:
    team_ids: list[int]
    max_concurrent_teams: int


@frozen
class StageInputs:
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


def _deadline(limits: ActivityLimits) -> float:
    return time.monotonic() + (limits.start_to_close - DEADLINE_MARGIN).total_seconds()


@activity.defn(name="llma-eval-suggestions-measure")
async def measure_eval_suggestions_activity(inputs: StageInputs) -> int:
    async with Heartbeater():
        suggestion_settings = await on_asyncify_pool(load_settings)()
        return await on_asyncify_pool(measure_stage)(
            inputs.team_id, inputs.run_id, settings=suggestion_settings, deadline=_deadline(MEASURE)
        )


@activity.defn(name="llma-eval-suggestions-screen")
async def screen_eval_suggestions_activity(inputs: StageInputs) -> int:
    async with Heartbeater():
        suggestion_settings = await on_asyncify_pool(load_settings)()
        return await on_asyncify_pool(screen_stage)(
            inputs.team_id,
            inputs.run_id,
            include_paid=inputs.include_paid,
            settings=suggestion_settings,
            deadline=_deadline(SCREEN),
        )


@activity.defn(name="llma-eval-suggestions-draft")
async def draft_eval_suggestions_activity(inputs: StageInputs) -> int:
    async with Heartbeater():
        suggestion_settings = await on_asyncify_pool(load_settings)()
        return await on_asyncify_pool(draft_stage)(
            inputs.team_id,
            inputs.run_id,
            include_paid=inputs.include_paid,
            settings=suggestion_settings,
            deadline=_deadline(DRAFT),
        )


@activity.defn(name="llma-eval-suggestions-publish")
async def publish_eval_suggestions_activity(inputs: StageInputs) -> int:
    return await on_asyncify_pool(publish_stage)(inputs.team_id, inputs.run_id)


def _options(limits: ActivityLimits, *, heartbeat: bool = True) -> dict[str, Any]:
    return {
        "start_to_close_timeout": limits.start_to_close,
        # Each activity has a schedule-to-close deadline, so worker queue time cannot outlast the workflow.
        "schedule_to_close_timeout": limits.schedule_to_close,
        **({"heartbeat_timeout": timedelta(minutes=2)} if heartbeat else {}),
        "retry_policy": RetryPolicy(maximum_attempts=limits.attempts, initial_interval=limits.retry_interval),
    }


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class EvalSuggestionsTeamWorkflow(PostHogWorkflow):
    inputs_cls = TeamRunInputs

    @workflow.run
    async def run(self, inputs: TeamRunInputs) -> int:
        info = workflow.info()
        # Known before the start activity runs, so a start that created the row and then failed is cleaned up too.
        run_id = inputs.run_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{info.workflow_id}/{info.run_id}"))
        stage = StageInputs(team_id=inputs.team_id, run_id=run_id, include_paid=inputs.include_paid)
        try:
            await workflow.execute_activity(
                start_eval_suggestions_run_activity,
                StartRunInputs(run=inputs, run_id=run_id),
                **_options(START_RUN, heartbeat=False),
            )
            await workflow.execute_activity(measure_eval_suggestions_activity, stage, **_options(MEASURE))
            paid: list[tuple[Callable, ActivityLimits]] = [
                (screen_eval_suggestions_activity, SCREEN),
                (draft_eval_suggestions_activity, DRAFT),
            ]
            for paid_activity, limits in paid:
                try:
                    await workflow.execute_activity(paid_activity, stage, **_options(limits))
                except ActivityError as error:
                    # The free cards still publish, and publish records the stage as unfinished.
                    workflow.logger.warning(
                        "eval_suggestions_paid_stage_failed",
                        extra={"team_id": inputs.team_id, "error": str(error.cause or error)},
                    )
            return await workflow.execute_activity(
                publish_eval_suggestions_activity, stage, **_options(PUBLISH, heartbeat=False)
            )
        except ActivityError as error:
            # Only the workflow marks a run failed, once a required stage has used up its attempts. An attempt that
            # timed out keeps running in its thread, and it must not fail the run a newer attempt is working on.
            await workflow.execute_activity(
                fail_eval_suggestions_run_activity,
                FailRunInputs(team_id=inputs.team_id, run_id=run_id, error=str(error.cause or error)),
                **_options(FAIL_RUN, heartbeat=False),
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
            # running ones finished. The batch id carries over, since the drafting budget is counted per batch.
            workflow.continue_as_new(
                CoordinatorInputs(remaining_team_ids=queue, batch_id=batch_id, max_concurrent_teams=concurrency)
            )
        return {"teams_succeeded": succeeded, "teams_failed": failed}


WORKFLOWS = [EvalSuggestionsCoordinatorWorkflow, EvalSuggestionsTeamWorkflow]
ACTIVITIES = [
    plan_eval_suggestions_activity,
    start_eval_suggestions_run_activity,
    measure_eval_suggestions_activity,
    screen_eval_suggestions_activity,
    draft_eval_suggestions_activity,
    publish_eval_suggestions_activity,
    fail_eval_suggestions_run_activity,
]
