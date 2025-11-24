from posthog.temporal.data_modeling.ducklake_copy_workflow import (
    DuckLakeCopyWorkflow,
    copy_model_to_ducklake_activity,
    prepare_ducklake_copy_metadata_activity,
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

WORKFLOWS = [RunWorkflow, DuckLakeCopyWorkflow]
ACTIVITIES = [
    finish_run_activity,
    start_run_activity,
    build_dag_activity,
    run_dag_activity,
    cancel_jobs_activity,
    fail_jobs_activity,
    create_job_model_activity,
    cleanup_running_jobs_activity,
    prepare_ducklake_copy_metadata_activity,
    copy_model_to_ducklake_activity,
]
