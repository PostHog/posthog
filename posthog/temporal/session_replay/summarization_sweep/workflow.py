"""Per-team summarization workflow.

Fires from a per-team schedule. Starts a `summarize-session` child per session
and ABANDONs them so they outlive this short workflow. Self-deletes its own
schedule if the team has been disabled since the last tick.
"""

import json
import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.summarization_sweep.constants import (
    FIND_ACTIVITY_TIMEOUT,
    MAX_SESSIONS_PER_TEAM,
    SESSION_LOOKBACK_MINUTES,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.summarization_sweep.models import (
    DeleteTeamScheduleInput,
    FindSessionsInput,
    SummarizeTeamSessionsInputs,
)

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL

# These imports pull in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from django.conf import settings

    from posthog.temporal.session_replay.session_summary.summarize_session import SummarizeSingleSessionWorkflow
    from posthog.temporal.session_replay.session_summary.types.single import SingleSessionSummaryInputs
    from posthog.temporal.session_replay.summarization_sweep.activities import (
        delete_team_schedule_activity,
        find_sessions_for_team_activity,
    )


@workflow.defn(name=WORKFLOW_NAME)
class SummarizeTeamSessionsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SummarizeTeamSessionsInputs:
        return SummarizeTeamSessionsInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: SummarizeTeamSessionsInputs) -> dict[str, Any]:
        result = await workflow.execute_activity(
            find_sessions_for_team_activity,
            args=[
                FindSessionsInput(
                    team_id=inputs.team_id,
                    lookback_minutes=SESSION_LOOKBACK_MINUTES,
                    max_sessions=MAX_SESSIONS_PER_TEAM,
                )
            ],
            start_to_close_timeout=FIND_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if result.team_disabled:
            # Fast-path so a just-disabled team doesn't do another cycle before
            # the reconciler cleans up on its next tick.
            await workflow.execute_activity(
                delete_team_schedule_activity,
                args=[DeleteTeamScheduleInput(team_id=inputs.team_id, dry_run=inputs.dry_run)],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return {
                "team_id": inputs.team_id,
                "team_disabled": True,
                "workflows_started": 0,
                "workflows_skipped_already_running": 0,
                "dry_run": inputs.dry_run,
            }

        if not result.session_ids or result.user_id is None:
            return {
                "team_id": inputs.team_id,
                "team_disabled": False,
                "workflows_started": 0,
                "workflows_skipped_already_running": 0,
                "dry_run": inputs.dry_run,
            }

        if inputs.dry_run:
            workflow.logger.info(
                "summarization_sweep.dry_run.would_start_children",
                extra={
                    "team_id": inputs.team_id,
                    "session_ids": result.session_ids,
                    "user_id": result.user_id,
                },
            )
            return {
                "team_id": inputs.team_id,
                "team_disabled": False,
                "workflows_started": 0,
                "workflows_skipped_already_running": 0,
                "dry_run": True,
            }

        start_results = await asyncio.gather(
            *(
                self._start_child(inputs.team_id, sid, result.user_id, result.user_distinct_id)
                for sid in result.session_ids
            ),
            return_exceptions=True,
        )
        started = 0
        skipped = 0
        failed = 0
        for r in start_results:
            if isinstance(r, BaseException):
                failed += 1
                workflow.logger.warning(
                    "summarization_sweep.start_child_failed",
                    extra={"team_id": inputs.team_id, "error": str(r)},
                )
            elif r:
                started += 1
            else:
                skipped += 1

        # All-fail is systemic (queue config, permissions, Temporal outage) — surface it.
        if failed > 0 and started == 0 and skipped == 0:
            raise ApplicationError(
                f"All {failed} child workflow starts failed for team {inputs.team_id}",
                type="AllChildStartsFailed",
            )

        return {
            "team_id": inputs.team_id,
            "team_disabled": False,
            "workflows_started": started,
            "workflows_skipped_already_running": skipped,
            "dry_run": False,
        }

    async def _start_child(
        self,
        team_id: int,
        session_id: str,
        user_id: int,
        user_distinct_id: str | None,
    ) -> bool:
        try:
            await workflow.start_child_workflow(
                "summarize-session",
                SingleSessionSummaryInputs(
                    session_id=session_id,
                    user_id=user_id,
                    user_distinct_id_to_log=user_distinct_id,
                    team_id=team_id,
                    redis_key_base=f"session-summary:single:{user_id}-{team_id}:{session_id}",
                    model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
                    video_based=True,
                ),
                id=SummarizeSingleSessionWorkflow.workflow_id_for(team_id, session_id),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                search_attributes=TypedSearchAttributes(
                    search_attributes=[SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team_id)]
                ),
                # Covers all three retry attempts + backoff (10m + 15m + 15m) with headroom.
                execution_timeout=timedelta(minutes=45),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=10),
                    backoff_coefficient=1.5,
                    maximum_interval=timedelta(minutes=15),
                ),
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )
            return True
        except WorkflowAlreadyStartedError:
            # `summaries_exist()` only catches completed summaries — in-progress
            # and between-retry cases surface here.
            return False
