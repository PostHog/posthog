"""Temporal workflow that polls duckgres's billing pull API on a schedule.

Two activities: the poll (fetch + persist — potentially tens of MB of rows that
can't cross the workflow boundary) records the watermark to ack, then — if there
is one — a small ack activity performs the POST. Splitting the ack means a
transient ack failure retries just the POST, not the whole fetch+persist.
Scheduled every 10 minutes (`posthog/temporal/schedule.py`) with overlap policy
SKIP, so two polls are never in flight at once.
"""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.duckgres_usage.activities import (
    ack_duckgres_usage,
    poll_duckgres_usage,
    set_duckgres_default_team,
)
from posthog.temporal.duckgres_usage.types import (
    PollDuckgresUsageInputs,
    PollDuckgresUsageResult,
    SetDuckgresDefaultTeamInputs,
)

POLL_DUCKGRES_USAGE_WORKFLOW = "poll-duckgres-usage"
POLL_DUCKGRES_USAGE_SCHEDULE_ID = "poll-duckgres-usage-schedule"
UPDATE_DUCKGRES_DEFAULT_TEAM_WORKFLOW = "update-duckgres-default-team"


@workflow.defn(name=POLL_DUCKGRES_USAGE_WORKFLOW)
class PollDuckgresUsageWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PollDuckgresUsageInputs:
        if not inputs:
            return PollDuckgresUsageInputs()
        return PollDuckgresUsageInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
        result = await workflow.execute_activity(
            poll_duckgres_usage,
            inputs,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
            heartbeat_timeout=timedelta(minutes=2),
        )
        # The poll committed the watermark (record-before-ack); acking is a small
        # POST in its own activity so a transient failure doesn't re-run the pull.
        if result.ack_watermark is not None:
            await workflow.execute_activity(
                ack_duckgres_usage,
                result.ack_watermark,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )
        # A dead default team surfaced by the poll: duckgres is stamping a team
        # that no longer exists for this org. Repoint it at the source, fire-and-
        # forget (ABANDON — it outlives this poll). Stable id + ALLOW_DUPLICATE so
        # repeated detections across polls don't stack: an in-flight repoint is
        # skipped, and a completed one may re-run (idempotent server-side).
        for org_id, team_id in result.default_team_repoints.items():
            try:
                await workflow.start_child_workflow(
                    UPDATE_DUCKGRES_DEFAULT_TEAM_WORKFLOW,
                    SetDuckgresDefaultTeamInputs(org_id=org_id, team_id=team_id),
                    id=UpdateDuckgresDefaultTeamWorkflow.workflow_id_for(org_id),
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    task_queue=workflow.info().task_queue,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
                )
            except WorkflowAlreadyStartedError:
                pass  # a repoint for this org is already running (a previous poll started it)
        return result


@workflow.defn(name=UPDATE_DUCKGRES_DEFAULT_TEAM_WORKFLOW)
class UpdateDuckgresDefaultTeamWorkflow(PostHogWorkflow):
    """Repoint one org's managed-warehouse default team in duckgres.

    Started fire-and-forget by the poll when it finds duckgres stamping a deleted
    default team. Its own workflow so the (mutating) control-plane PUT retries
    independently of the pull and can't wedge it.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SetDuckgresDefaultTeamInputs:
        return SetDuckgresDefaultTeamInputs(**json.loads(inputs[0]))

    @staticmethod
    def workflow_id_for(org_id: str) -> str:
        # Stable per org so concurrent polls dedup (WorkflowAlreadyStartedError).
        return f"duckgres-set-default-team:{org_id}"

    @workflow.run
    async def run(self, inputs: SetDuckgresDefaultTeamInputs) -> None:
        await workflow.execute_activity(
            set_duckgres_default_team,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
        )
