from posthog.temporal.data_modeling.run_workflow import (
    RunWorkflow,
    build_dag_activity,
    create_table_activity,
    finish_run_activity,
    run_dag_activity,
    start_run_activity,
    cancel_jobs_activity,
    fail_jobs_activity,
    create_job_model_activity,
    get_upstream_dag_activity,
    run_single_model_activity,
    update_saved_query_status,
    create_jobs_for_materialized_views_activity,
)

WORKFLOWS = [RunWorkflow]
ACTIVITIES = [
    finish_run_activity,
    start_run_activity,
    build_dag_activity,
    run_dag_activity,
    create_table_activity,
    cancel_jobs_activity,
    fail_jobs_activity,
    create_job_model_activity,
    get_upstream_dag_activity,
    run_single_model_activity,
    update_saved_query_status,
    create_jobs_for_materialized_views_activity,
]
