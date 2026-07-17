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
from posthog.temporal.delete_teams.workflows import (
    DeleteOrganizationWorkflow,
    DeleteProjectDataWorkflow,
    DeleteTeamsDataWorkflow,
)

WORKFLOWS = [
    DeleteTeamsDataWorkflow,
    DeleteProjectDataWorkflow,
    DeleteOrganizationWorkflow,
]

ACTIVITIES = [
    queue_recording_deletions_activity,
    delete_misc_small_tables_activity,
    delete_personless_distinct_ids_activity,
    delete_cohort_members_activity,
    delete_groups_activity,
    delete_team_persons_activity,
    delete_batch_exports_activity,
    delete_data_modeling_schedules_activity,
    delete_team_records_activity,
    enqueue_clickhouse_deletion_activity,
    delete_project_record_activity,
    delete_organization_record_activity,
    send_project_deleted_email_activity,
    send_organization_deleted_email_activity,
]
