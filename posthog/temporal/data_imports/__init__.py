from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    create_external_data_job_model_activity,
    create_source_templates,
    import_data_activity,
    update_external_data_job_model,
    validate_schema_activity,
    check_schedule_activity,
)

WORKFLOWS = [ExternalDataJobWorkflow]

ACTIVITIES = [
    create_external_data_job_model_activity,
    update_external_data_job_model,
    import_data_activity,
    validate_schema_activity,
    create_source_templates,
    check_schedule_activity,
]
