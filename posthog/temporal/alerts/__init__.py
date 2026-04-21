from posthog.temporal.alerts.activities import (
    cleanup_alert_checks,
    evaluate_alert,
    notify_alert,
    prepare_alert,
    report_alerts_backlog,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.workflows import (
    AlertsBacklogWorkflow,
    CheckAlertWorkflow,
    CleanupAlertChecksWorkflow,
    RunInvestigationSafetyNetWorkflow,
    ScheduleDueAlertChecksWorkflow,
)

WORKFLOWS = [
    ScheduleDueAlertChecksWorkflow,
    CheckAlertWorkflow,
    RunInvestigationSafetyNetWorkflow,
    CleanupAlertChecksWorkflow,
    AlertsBacklogWorkflow,
]

ACTIVITIES = [
    retrieve_due_alerts,
    prepare_alert,
    evaluate_alert,
    notify_alert,
    run_investigation_safety_net,
    cleanup_alert_checks,
    report_alerts_backlog,
]
