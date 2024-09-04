from posthog.temporal.data_modeling.run_workflow import (
    RunWorkflow,
    build_dag_activity,
    finish_run_activity,
    run_dag_activity,
    start_run_activity,
)

WORKFLOWS = [RunWorkflow]
ACTIVITIES = [finish_run_activity, start_run_activity, build_dag_activity, run_dag_activity]
