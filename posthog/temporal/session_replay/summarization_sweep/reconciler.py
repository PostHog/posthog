"""Syncs per-team schedules with SignalSourceConfig on every tick.

Each schedule carries a config-fingerprint search attribute; mismatches with the
freshly-computed fingerprint trigger a rewrite, so UI edits propagate within one
RECONCILER_INTERVAL.
"""

import asyncio
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_replay.summarization_sweep.constants import (
    LIST_ENABLED_TEAMS_TIMEOUT,
    LIST_SCHEDULES_TIMEOUT,
    RECONCILER_WORKFLOW_NAME,
    UPSERT_SCHEDULE_TIMEOUT,
)
from posthog.temporal.session_replay.summarization_sweep.types import (
    DeleteTeamScheduleInput,
    ReconcileSchedulesInputs,
    ReconcileSchedulesResult,
    UpsertTeamScheduleInput,
)

# `activities` pulls in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from posthog.temporal.session_replay.summarization_sweep.activities import (
        delete_team_schedule_activity,
        list_enabled_teams_activity,
        list_summarization_schedule_team_ids_activity,
        upsert_team_schedule_activity,
    )


@workflow.defn(name=RECONCILER_WORKFLOW_NAME)
class ReconcileSummarizationSchedulesWorkflow(PostHogWorkflow):
    inputs_cls = ReconcileSchedulesInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: ReconcileSchedulesInputs) -> dict[str, Any]:
        # A team toggled between the two listings recovers on the next tick.
        enabled_fingerprints, existing_fingerprints = await asyncio.gather(
            workflow.execute_activity(
                list_enabled_teams_activity,
                start_to_close_timeout=LIST_ENABLED_TEAMS_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
            workflow.execute_activity(
                list_summarization_schedule_team_ids_activity,
                start_to_close_timeout=LIST_SCHEDULES_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )
        enabled = set(enabled_fingerprints)
        existing = set(existing_fingerprints)
        # Untagged legacy schedules surface as None and naturally drift on first tick.
        drifted = {tid for tid in (enabled & existing) if existing_fingerprints[tid] != enabled_fingerprints[tid]}
        to_upsert = sorted((enabled - existing) | drifted)
        to_delete = sorted(existing - enabled)

        upsert_results, delete_results = await asyncio.gather(
            self._fan_out(
                to_upsert,
                lambda tid: workflow.execute_activity(
                    upsert_team_schedule_activity,
                    UpsertTeamScheduleInput(team_id=tid),
                    start_to_close_timeout=UPSERT_SCHEDULE_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                ),
            ),
            self._fan_out(
                to_delete,
                lambda tid: workflow.execute_activity(
                    delete_team_schedule_activity,
                    DeleteTeamScheduleInput(team_id=tid),
                    start_to_close_timeout=UPSERT_SCHEDULE_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3),
                ),
            ),
        )
        result = ReconcileSchedulesResult(
            upserted_team_ids=[tid for tid, ok in zip(to_upsert, upsert_results) if ok],
            deleted_team_ids=[tid for tid, ok in zip(to_delete, delete_results) if ok],
            failed_upsert_team_ids=[tid for tid, ok in zip(to_upsert, upsert_results) if not ok],
            failed_delete_team_ids=[tid for tid, ok in zip(to_delete, delete_results) if not ok],
        )
        if result.failed_upsert_team_ids or result.failed_delete_team_ids:
            workflow.logger.warning(
                "summarization_sweep.reconcile_partial_failure",
                extra={
                    "failed_upsert": result.failed_upsert_team_ids,
                    "failed_delete": result.failed_delete_team_ids,
                },
            )
        return {
            "upserted": len(result.upserted_team_ids),
            "deleted": len(result.deleted_team_ids),
            "failed_upsert": len(result.failed_upsert_team_ids),
            "failed_delete": len(result.failed_delete_team_ids),
        }

    async def _fan_out(self, team_ids: list[int], make_coro) -> list[bool]:
        if not team_ids:
            return []
        # return_exceptions so one team's failure doesn't block the others.
        results = await asyncio.gather(*(make_coro(tid) for tid in team_ids), return_exceptions=True)
        return [not isinstance(r, BaseException) for r in results]


async def create_summarization_sweep_reconciler_schedule(client) -> None:
    """Create or update the global reconciler schedule. Called from worker startup."""
    from django.conf import settings

    from temporalio import common
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleIntervalSpec,
        ScheduleOverlapPolicy,
        SchedulePolicy,
        ScheduleSpec,
    )

    from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
    from posthog.temporal.session_replay.summarization_sweep.constants import (
        RECONCILER_EXECUTION_TIMEOUT,
        RECONCILER_INTERVAL,
        RECONCILER_SCHEDULE_ID,
        RECONCILER_WORKFLOW_ID,
        RECONCILER_WORKFLOW_NAME,
    )

    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            RECONCILER_WORKFLOW_NAME,
            ReconcileSchedulesInputs(),
            id=RECONCILER_WORKFLOW_ID,
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            execution_timeout=RECONCILER_EXECUTION_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=RECONCILER_INTERVAL)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=RECONCILER_INTERVAL,
        ),
    )
    if await a_schedule_exists(client, RECONCILER_SCHEDULE_ID):
        await a_update_schedule(client, RECONCILER_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, RECONCILER_SCHEDULE_ID, schedule, trigger_immediately=True)
