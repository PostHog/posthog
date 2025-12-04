from posthog.temporal.ducklake.ducklake_copy_workflow import (
    DuckLakeCopyDataModelingWorkflow,
    copy_data_modeling_model_to_ducklake_activity,
    ducklake_copy_workflow_gate_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    verify_ducklake_copy_activity,
)

WORKFLOWS = [DuckLakeCopyDataModelingWorkflow]
ACTIVITIES = [
    prepare_data_modeling_ducklake_metadata_activity,
    ducklake_copy_workflow_gate_activity,
    copy_data_modeling_model_to_ducklake_activity,
    verify_ducklake_copy_activity,
]
