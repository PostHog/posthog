from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    create_external_data_job_model,
    update_external_data_job_model,
    run_external_data_job,
    validate_schema_activity,
)

WORKFLOWS = [ExternalDataJobWorkflow]

ACTIVITIES = [
    create_external_data_job_model,
    update_external_data_job_model,
    run_external_data_job,
    validate_schema_activity,
]
