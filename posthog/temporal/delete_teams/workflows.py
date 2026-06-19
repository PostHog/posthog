import datetime as dt

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.delete_teams.activities import (
    delete_batch_exports_activity,
    delete_cohort_members_activity,
    delete_data_modeling_schedules_activity,
    delete_groups_activity,
    delete_misc_small_tables_activity,
    delete_organization_record_activity,
    delete_personless_distinct_ids_activity,
    delete_project_record_activity,
    delete_team_persons_activity,
    delete_team_records_activity,
    enqueue_clickhouse_deletion_activity,
    queue_recording_deletions_activity,
    send_organization_deleted_email_activity,
    send_project_deleted_email_activity,
)
from posthog.temporal.delete_teams.types import (
    DeleteOrganizationWorkflowInputs,
    DeleteProjectDataWorkflowInputs,
    DeleteTeamsDataWorkflowInputs,
    OrganizationEmailInputs,
    OrganizationRecordInputs,
    ProjectEmailInputs,
    ProjectRecordInputs,
    TeamDataActivityInputs,
)

# The bulky deletes are idempotent ("delete next N rows for this team until empty"), so they
# can retry indefinitely on transient DB errors — the data only ever shrinks, and a restarted
# activity just resumes. Deterministic failures (e.g. a ProtectedError from a PROTECT FK the
# phase ordering doesn't account for, or a RecursionError decoding a deeply-nested JSON column on
# a cascaded row) are non-retryable so the workflow fails fast and surfaces instead of looping forever.
DELETE_RETRY_POLICY = temporalio.common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=10),
    maximum_interval=dt.timedelta(seconds=360),
    maximum_attempts=0,
    non_retryable_error_types=["ProtectedError", "RecursionError"],
)
# Bounded retries for the lighter orchestration / side-effect activities.
SIDE_EFFECT_RETRY_POLICY = temporalio.common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=5),
    maximum_interval=dt.timedelta(seconds=60),
    maximum_attempts=5,
)

HEAVY_ACTIVITY_TIMEOUT = dt.timedelta(hours=2)
HEAVY_HEARTBEAT_TIMEOUT = dt.timedelta(seconds=60)
LIGHT_ACTIVITY_TIMEOUT = dt.timedelta(minutes=10)
LIGHT_HEARTBEAT_TIMEOUT = dt.timedelta(seconds=60)
EMAIL_ACTIVITY_TIMEOUT = dt.timedelta(minutes=2)
EMAIL_HEARTBEAT_TIMEOUT = dt.timedelta(seconds=30)

# Bulky Postgres phases, run in dependency-safe order (each its own retryable activity).
BULKY_POSTGRES_ACTIVITIES = (
    delete_misc_small_tables_activity,
    delete_personless_distinct_ids_activity,
    delete_cohort_members_activity,
    delete_groups_activity,
    delete_team_persons_activity,
)


@temporalio.workflow.defn(name="delete-teams-data")
class DeleteTeamsDataWorkflow(PostHogWorkflow):
    """Delete all child data and the team rows for a set of teams.

    The reusable core: composed as a child workflow by both ``DeleteProjectDataWorkflow``
    and ``DeleteOrganizationWorkflow``. Mirrors the phase order of the legacy
    ``_delete_teams_and_data`` Celery path, with each phase as an independently retryable,
    heartbeating activity.
    """

    inputs_cls = DeleteTeamsDataWorkflowInputs

    @temporalio.workflow.run
    async def run(self, inputs: DeleteTeamsDataWorkflowInputs) -> None:
        if not inputs.team_ids:
            return

        team_inputs = TeamDataActivityInputs(team_ids=inputs.team_ids, user_id=inputs.user_id)

        # Start the autonomous session-replay recording deletion (fire-and-forget). Best-effort:
        # queuing recording deletion is not a prerequisite for removing the team's data, so if it
        # exhausts its retries we log and carry on rather than wedging the whole deletion. Recordings
        # left behind are reaped by their own retention/TTL.
        try:
            await temporalio.workflow.execute_activity(
                queue_recording_deletions_activity,
                team_inputs,
                start_to_close_timeout=LIGHT_ACTIVITY_TIMEOUT,
                heartbeat_timeout=LIGHT_HEARTBEAT_TIMEOUT,
                retry_policy=SIDE_EFFECT_RETRY_POLICY,
            )
        except temporalio.exceptions.ActivityError:
            temporalio.workflow.logger.warning(
                "queue_recording_deletions_activity failed; continuing team deletion without it",
                exc_info=True,
            )

        for activity in BULKY_POSTGRES_ACTIVITIES:
            await temporalio.workflow.execute_activity(
                activity,
                team_inputs,
                start_to_close_timeout=HEAVY_ACTIVITY_TIMEOUT,
                heartbeat_timeout=HEAVY_HEARTBEAT_TIMEOUT,
                retry_policy=DELETE_RETRY_POLICY,
            )

        # Temporal schedules owned by the teams must be torn down explicitly (CASCADE won't).
        await temporalio.workflow.execute_activity(
            delete_batch_exports_activity,
            team_inputs,
            start_to_close_timeout=LIGHT_ACTIVITY_TIMEOUT,
            heartbeat_timeout=LIGHT_HEARTBEAT_TIMEOUT,
            retry_policy=SIDE_EFFECT_RETRY_POLICY,
        )
        await temporalio.workflow.execute_activity(
            delete_data_modeling_schedules_activity,
            team_inputs,
            start_to_close_timeout=LIGHT_ACTIVITY_TIMEOUT,
            heartbeat_timeout=LIGHT_HEARTBEAT_TIMEOUT,
            retry_policy=SIDE_EFFECT_RETRY_POLICY,
        )

        # The bulky children are gone, so the Team row delete is cheap, then hand off to ClickHouse.
        await temporalio.workflow.execute_activity(
            delete_team_records_activity,
            team_inputs,
            start_to_close_timeout=LIGHT_ACTIVITY_TIMEOUT,
            heartbeat_timeout=LIGHT_HEARTBEAT_TIMEOUT,
            retry_policy=DELETE_RETRY_POLICY,
        )
        await temporalio.workflow.execute_activity(
            enqueue_clickhouse_deletion_activity,
            team_inputs,
            start_to_close_timeout=LIGHT_ACTIVITY_TIMEOUT,
            heartbeat_timeout=LIGHT_HEARTBEAT_TIMEOUT,
            retry_policy=SIDE_EFFECT_RETRY_POLICY,
        )


async def _delete_teams_data_child(inputs: DeleteTeamsDataWorkflowInputs, workflow_id: str) -> None:
    await temporalio.workflow.execute_child_workflow(
        DeleteTeamsDataWorkflow.run,
        inputs,
        id=workflow_id,
    )


@temporalio.workflow.defn(name="delete-project-data")
class DeleteProjectDataWorkflow(PostHogWorkflow):
    """Replaces ``delete_project_data_and_notify_task`` — project or environment-only deletion."""

    inputs_cls = DeleteProjectDataWorkflowInputs

    @temporalio.workflow.run
    async def run(self, inputs: DeleteProjectDataWorkflowInputs) -> None:
        if inputs.team_ids:
            await _delete_teams_data_child(
                DeleteTeamsDataWorkflowInputs(team_ids=inputs.team_ids, user_id=inputs.user_id),
                f"{temporalio.workflow.info().workflow_id}-teams-data",
            )

        # For environment-only deletion (project_id is None) the team rows are already gone.
        if inputs.project_id is not None:
            await temporalio.workflow.execute_activity(
                delete_project_record_activity,
                ProjectRecordInputs(project_id=inputs.project_id),
                start_to_close_timeout=LIGHT_ACTIVITY_TIMEOUT,
                heartbeat_timeout=LIGHT_HEARTBEAT_TIMEOUT,
                retry_policy=DELETE_RETRY_POLICY,
            )

        await temporalio.workflow.execute_activity(
            send_project_deleted_email_activity,
            ProjectEmailInputs(user_id=inputs.user_id, project_name=inputs.project_name),
            start_to_close_timeout=EMAIL_ACTIVITY_TIMEOUT,
            heartbeat_timeout=EMAIL_HEARTBEAT_TIMEOUT,
            retry_policy=SIDE_EFFECT_RETRY_POLICY,
        )


@temporalio.workflow.defn(name="delete-organization")
class DeleteOrganizationWorkflow(PostHogWorkflow):
    """Replaces ``delete_organization_data_and_notify_task``."""

    inputs_cls = DeleteOrganizationWorkflowInputs

    @temporalio.workflow.run
    async def run(self, inputs: DeleteOrganizationWorkflowInputs) -> None:
        if inputs.team_ids:
            await _delete_teams_data_child(
                DeleteTeamsDataWorkflowInputs(team_ids=inputs.team_ids, user_id=inputs.user_id),
                f"{temporalio.workflow.info().workflow_id}-teams-data",
            )

        # Deleting the org row cascades any remaining Projects; the teams are already gone.
        await temporalio.workflow.execute_activity(
            delete_organization_record_activity,
            OrganizationRecordInputs(organization_id=inputs.organization_id, user_id=inputs.user_id),
            start_to_close_timeout=LIGHT_ACTIVITY_TIMEOUT,
            heartbeat_timeout=LIGHT_HEARTBEAT_TIMEOUT,
            retry_policy=DELETE_RETRY_POLICY,
        )

        await temporalio.workflow.execute_activity(
            send_organization_deleted_email_activity,
            OrganizationEmailInputs(
                user_id=inputs.user_id,
                organization_name=inputs.organization_name,
                project_names=inputs.project_names,
            ),
            start_to_close_timeout=EMAIL_ACTIVITY_TIMEOUT,
            heartbeat_timeout=EMAIL_HEARTBEAT_TIMEOUT,
            retry_policy=SIDE_EFFECT_RETRY_POLICY,
        )
