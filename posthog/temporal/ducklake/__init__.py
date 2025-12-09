from posthog.temporal.ducklake.compaction_workflow import DucklakeCompactionWorkflow, run_ducklake_compaction
from posthog.temporal.ducklake.ducklake_copy_workflow import (
    DuckLakeCopyDataModelingWorkflow,
    copy_data_modeling_model_to_ducklake_activity,
    ducklake_copy_workflow_gate_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    verify_ducklake_copy_activity,
)

WORKFLOWS = [DuckLakeCopyDataModelingWorkflow, DucklakeCompactionWorkflow]
ACTIVITIES = [
    prepare_data_modeling_ducklake_metadata_activity,
    ducklake_copy_workflow_gate_activity,
    copy_data_modeling_model_to_ducklake_activity,
    verify_ducklake_copy_activity,
    run_ducklake_compaction,
]
