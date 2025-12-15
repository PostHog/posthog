from posthog.temporal.weekly_digest.activities import (
    count_organizations,
    count_teams,
    generate_dashboard_lookup,
    generate_event_definition_lookup,
    generate_experiment_completed_lookup,
    generate_experiment_launched_lookup,
    generate_external_data_source_lookup,
    generate_feature_flag_lookup,
    generate_filter_lookup,
    generate_organization_digest_batch,
    generate_recording_lookup,
    generate_survey_lookup,
    generate_user_notification_lookup,
    send_weekly_digest_batch,
)
from posthog.temporal.weekly_digest.workflows import (
    GenerateDigestDataWorkflow,
    SendWeeklyDigestWorkflow,
    WeeklyDigestWorkflow,
)

WORKFLOWS = [
    WeeklyDigestWorkflow,
    GenerateDigestDataWorkflow,
    SendWeeklyDigestWorkflow,
]

ACTIVITIES = [
    generate_dashboard_lookup,
    generate_event_definition_lookup,
    generate_experiment_completed_lookup,
    generate_experiment_launched_lookup,
    generate_external_data_source_lookup,
    generate_survey_lookup,
    generate_feature_flag_lookup,
    generate_user_notification_lookup,
    generate_organization_digest_batch,
    count_organizations,
    count_teams,
    send_weekly_digest_batch,
    generate_filter_lookup,
    generate_recording_lookup,
]
