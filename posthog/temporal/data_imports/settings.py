from posthog.temporal.data_imports.ducklake_copy_data_imports_workflow import (
    DuckLakeCopyDataImportsWorkflow,
    copy_data_imports_to_ducklake_activity,
    ducklake_copy_data_imports_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
    verify_data_imports_ducklake_copy_activity,
)
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

WORKFLOWS = [ExternalDataJobWorkflow, DuckLakeCopyDataImportsWorkflow]

ACTIVITIES = [
    create_external_data_job_model_activity,
    update_external_data_job_model,
    import_data_activity_sync,
    create_source_templates,
    check_billing_limits_activity,
    sync_new_schemas_activity,
    calculate_table_size_activity,
    trigger_schedule_buffer_one_activity,
    ducklake_copy_data_imports_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
    copy_data_imports_to_ducklake_activity,
    verify_data_imports_ducklake_copy_activity,
]
