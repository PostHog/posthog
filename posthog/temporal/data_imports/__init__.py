from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    create_external_data_job_model_activity,
    create_source_templates,
    import_data_activity,
    import_data_activity_sync,
    update_external_data_job_model,
    check_schedule_activity,
    check_billing_limits_activity,
    sync_new_schemas_activity,
)

WORKFLOWS = [ExternalDataJobWorkflow]

ACTIVITIES = [
    create_external_data_job_model_activity,
    update_external_data_job_model,
    import_data_activity,
    import_data_activity_sync,
    create_source_templates,
    check_schedule_activity,
    check_billing_limits_activity,
    sync_new_schemas_activity,
]
