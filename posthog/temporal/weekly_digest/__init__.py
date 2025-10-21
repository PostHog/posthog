from posthog.temporal.weekly_digest.activities import (
    generate_dashboard_lookup,
    generate_event_definition_lookup,
    generate_experiment_lookup,
    generate_external_data_source_lookup,
    generate_feature_flag_lookup,
    generate_survey_lookup,
    generate_user_notification_lookup,
)
from posthog.temporal.weekly_digest.workflows import GenerateDigestDataWorkflow, WeeklyDigestWorkflow

WORKFLOWS = [
    WeeklyDigestWorkflow,
    GenerateDigestDataWorkflow,
]

ACTIVITIES = [
    generate_dashboard_lookup,
    generate_event_definition_lookup,
    generate_experiment_lookup,
    generate_external_data_source_lookup,
    generate_survey_lookup,
    generate_feature_flag_lookup,
    generate_user_notification_lookup,
]
