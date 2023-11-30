from posthog.temporal.data_imports.external_data_job import *

WORKFLOWS = [ExternalDataJobWorkflow]

ACTIVITIES = [
    create_external_data_job_model,
    update_external_data_job_model,
    run_external_data_job,
    move_draft_to_production_activity,
    validate_schema_activity,
]
