from posthog.temporal.data_modeling.activities import (
    create_data_modeling_job_activity,
    fail_materialization_activity,
    materialize_view_activity,
    prepare_queryable_table_activity,
    succeed_materialization_activity,
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
from posthog.temporal.data_modeling.workflows import MaterializeViewWorkflow

WORKFLOWS = [RunWorkflow, MaterializeViewWorkflow]
ACTIVITIES = [
    create_data_modeling_job_activity,
    fail_materialization_activity,
    materialize_view_activity,
    prepare_queryable_table_activity,
    succeed_materialization_activity,
    finish_run_activity,
    start_run_activity,
    build_dag_activity,
    run_dag_activity,
    cancel_jobs_activity,
    fail_jobs_activity,
    create_job_model_activity,
    cleanup_running_jobs_activity,
]
