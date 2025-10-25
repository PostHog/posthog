from posthog.temporal.data_imports.deltalake_compaction_job import DeltalakeCompactionJobWorkflow, run_compaction
from posthog.temporal.data_imports.external_data_job import (
    ExternalDataJobWorkflow,
    calculate_table_size_activity,
    check_billing_limits_activity,
    create_external_data_job_model_activity,
    create_source_templates,
    import_data_activity_sync,
    sync_new_schemas_activity,
    trigger_schedule_buffer_one_activity,
    update_external_data_job_model,
)

WORKFLOWS = [ExternalDataJobWorkflow, DeltalakeCompactionJobWorkflow]

ACTIVITIES = [
    create_external_data_job_model_activity,
    update_external_data_job_model,
    import_data_activity_sync,
    create_source_templates,
    check_billing_limits_activity,
    sync_new_schemas_activity,
    run_compaction,
    calculate_table_size_activity,
    trigger_schedule_buffer_one_activity,
]
