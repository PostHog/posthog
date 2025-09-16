from posthog.temporal.data_snapshots.run_workflow import RunWorkflow, run_snapshot_activity

WORKFLOWS = [RunWorkflow]
ACTIVITIES = [
    run_snapshot_activity,
]
