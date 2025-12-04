from posthog.temporal.data_modeling.ducklake_copy_workflow import (
    DuckLakeCopyDataModelingWorkflow,
    copy_data_modeling_model_to_ducklake_activity,
    ducklake_copy_workflow_gate_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    verify_ducklake_copy_activity,
)
from posthog.temporal.data_modeling.run_workflow import (
    RunWorkflow,
    build_dag_activity,
    cancel_jobs_activity,
    cleanup_running_jobs_activity,
    create_job_model_activity,
    fail_jobs_activity,
    finish_run_activity,
    run_dag_activity,
    start_run_activity,
)

WORKFLOWS = [RunWorkflow, DuckLakeCopyDataModelingWorkflow]
ACTIVITIES = [
    finish_run_activity,
    start_run_activity,
    build_dag_activity,
    run_dag_activity,
    cancel_jobs_activity,
    fail_jobs_activity,
    create_job_model_activity,
    cleanup_running_jobs_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    ducklake_copy_workflow_gate_activity,
    copy_data_modeling_model_to_ducklake_activity,
    verify_ducklake_copy_activity,
]
