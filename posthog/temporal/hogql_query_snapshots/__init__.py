from posthog.temporal.hogql_query_snapshots.run_workflow import (
    RunWorkflow,
    create_snapshot_job_activity,
    finish_snapshot_job_activity,
    run_snapshot_activity,
)

WORKFLOWS = [RunWorkflow]
ACTIVITIES = [
    run_snapshot_activity,
    create_snapshot_job_activity,
    finish_snapshot_job_activity,
]
