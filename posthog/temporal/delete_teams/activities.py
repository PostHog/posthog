import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.delete_teams.types import (
    OrganizationEmailInputs,
    OrganizationRecordInputs,
    ProjectEmailInputs,
    ProjectRecordInputs,
    TeamDataActivityInputs,
)


def _resolve_deleted_by(user_id: int) -> str:
    from posthog.models.user import User

    user = User.objects.filter(id=user_id).first()
    return user.email if user else f"deleted_user_id:{user_id}"


@temporalio.activity.defn
async def queue_recording_deletions_activity(inputs: TeamDataActivityInputs) -> None:
    """Start the autonomous session-replay recording-deletion workflows for each team."""
    async with Heartbeater():
        from posthog.tasks.tasks import _queue_delete_team_recordings

        deleted_by = await database_sync_to_async_pool(_resolve_deleted_by)(inputs.user_id)
        await database_sync_to_async_pool(_queue_delete_team_recordings)(inputs.team_ids, deleted_by)


@temporalio.activity.defn
async def delete_misc_small_tables_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import _delete_misc_small_tables_for_teams

        await database_sync_to_async_pool(_delete_misc_small_tables_for_teams)(inputs.team_ids)


@temporalio.activity.defn
async def delete_personless_distinct_ids_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import _delete_personless_distinct_ids_for_teams

        await database_sync_to_async_pool(_delete_personless_distinct_ids_for_teams)(inputs.team_ids)


@temporalio.activity.defn
async def delete_cohort_members_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import _delete_cohort_members_for_all_teams

        await database_sync_to_async_pool(_delete_cohort_members_for_all_teams)(inputs.team_ids)


@temporalio.activity.defn
async def delete_groups_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import _delete_group_type_mappings_for_teams, _delete_groups_for_teams

        await database_sync_to_async_pool(_delete_groups_for_teams)(inputs.team_ids)
        await database_sync_to_async_pool(_delete_group_type_mappings_for_teams)(inputs.team_ids)


@temporalio.activity.defn
async def delete_team_persons_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import _delete_persons_for_teams

        await database_sync_to_async_pool(_delete_persons_for_teams)(inputs.team_ids)


@temporalio.activity.defn
async def delete_batch_exports_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import delete_batch_exports

        await database_sync_to_async_pool(delete_batch_exports)(inputs.team_ids)


@temporalio.activity.defn
async def delete_data_modeling_schedules_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import delete_data_modeling_schedules

        await database_sync_to_async_pool(delete_data_modeling_schedules)(inputs.team_ids)


@temporalio.activity.defn
async def delete_team_records_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import delete_team_records

        try:
            await database_sync_to_async_pool(delete_team_records)(inputs.team_ids)
        except RecursionError:
            # The cascade delete materializes full rows for models with delete signals, which
            # decodes their JSON columns via json.loads. A pathologically deeply-nested JSON
            # value (deep enough that Postgres stores it but json.loads cannot decode it under
            # Python's fixed C-recursion limit) overflows here. Retrying is futile — the data is
            # unchanged — and the multi-thousand-frame traceback exceeds Temporal's failure-size
            # limit, so re-raise a small, non-retryable error that surfaces cleanly instead.
            raise ApplicationError(
                f"Recursion limit exceeded deleting team records for {inputs.team_ids}; a cascaded "
                "row most likely holds a deeply-nested JSON value that json.loads cannot decode. "
                "Repair that row before retrying.",
                type="RecursionError",
                non_retryable=True,
            ) from None


def _enqueue_clickhouse_deletion(team_ids: list[int], user_id: int) -> None:
    from posthog.models.async_deletion import AsyncDeletion, DeletionType
    from posthog.models.user import User

    user = User.objects.filter(id=user_id).first()
    AsyncDeletion.objects.bulk_create(
        [
            AsyncDeletion(
                deletion_type=DeletionType.Team,
                team_id=team_id,
                key=str(team_id),
                created_by=user,
            )
            for team_id in team_ids
        ],
        ignore_conflicts=True,
    )


@temporalio.activity.defn
async def enqueue_clickhouse_deletion_activity(inputs: TeamDataActivityInputs) -> None:
    async with Heartbeater():
        await database_sync_to_async_pool(_enqueue_clickhouse_deletion)(inputs.team_ids, inputs.user_id)


@temporalio.activity.defn
async def delete_project_record_activity(inputs: ProjectRecordInputs) -> None:
    async with Heartbeater():
        from posthog.models.team.util import delete_project_record

        await database_sync_to_async_pool(delete_project_record)(inputs.project_id)


def _delete_organization_record(organization_id: str, user_id: int) -> None:
    from posthog.event_usage import report_organization_deletion_completed
    from posthog.models.team.util import delete_organization_record

    delete_organization_record(organization_id)
    report_organization_deletion_completed(user_id=user_id, organization_id=organization_id)


@temporalio.activity.defn
async def delete_organization_record_activity(inputs: OrganizationRecordInputs) -> None:
    async with Heartbeater():
        await database_sync_to_async_pool(_delete_organization_record)(inputs.organization_id, inputs.user_id)


def _send_project_deleted_email(user_id: int, project_name: str) -> None:
    from posthog.email import is_email_available
    from posthog.tasks.email import send_project_deleted_email

    if is_email_available():
        send_project_deleted_email.delay(user_id=user_id, project_name=project_name)


@temporalio.activity.defn
async def send_project_deleted_email_activity(inputs: ProjectEmailInputs) -> None:
    async with Heartbeater():
        await database_sync_to_async_pool(_send_project_deleted_email)(inputs.user_id, inputs.project_name)


def _send_organization_deleted_email(user_id: int, organization_name: str, project_names: list[str]) -> None:
    from posthog.email import is_email_available
    from posthog.tasks.email import send_organization_deleted_email

    if is_email_available():
        send_organization_deleted_email.delay(
            user_id=user_id, organization_name=organization_name, project_names=project_names
        )


@temporalio.activity.defn
async def send_organization_deleted_email_activity(inputs: OrganizationEmailInputs) -> None:
    async with Heartbeater():
        await database_sync_to_async_pool(_send_organization_deleted_email)(
            inputs.user_id, inputs.organization_name, inputs.project_names
        )
