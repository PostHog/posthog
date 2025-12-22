from posthog.temporal.ducklake.compaction_workflow import DucklakeCompactionWorkflow, run_ducklake_compaction
from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import (
    DuckLakeCopyDataImportsWorkflow,
    copy_data_imports_to_ducklake_activity,
    ducklake_copy_data_imports_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
    verify_data_imports_ducklake_copy_activity,
)
from posthog.temporal.ducklake.ducklake_copy_data_modeling_workflow import (
    DuckLakeCopyDataModelingWorkflow,
    copy_data_modeling_model_to_ducklake_activity,
    ducklake_copy_workflow_gate_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    verify_ducklake_copy_activity,
)

WORKFLOWS = [DucklakeCompactionWorkflow, DuckLakeCopyDataImportsWorkflow, DuckLakeCopyDataModelingWorkflow]
ACTIVITIES = [
    copy_data_imports_to_ducklake_activity,
    copy_data_modeling_model_to_ducklake_activity,
    ducklake_copy_data_imports_gate_activity,
    ducklake_copy_workflow_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    run_ducklake_compaction,
    verify_data_imports_ducklake_copy_activity,
    verify_ducklake_copy_activity,
]
