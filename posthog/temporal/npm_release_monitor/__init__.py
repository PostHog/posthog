from posthog.temporal.npm_release_monitor.activities import (
    correlate_releases,
    fetch_github_workflow_runs,
    fetch_npm_versions,
    send_alerts,
)
from posthog.temporal.npm_release_monitor.workflow import NpmReleaseMonitorWorkflow

WORKFLOWS = [
    NpmReleaseMonitorWorkflow,
]

ACTIVITIES = [
    fetch_npm_versions,
    fetch_github_workflow_runs,
    correlate_releases,
    send_alerts,
]
