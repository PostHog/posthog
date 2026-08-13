from posthog.temporal.alerts.activities import (
    cleanup_alert_checks,
    enqueue_alert_checks,
    evaluate_alert,
    notify_alert,
    prepare_alert,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.workflows import (
    AlertEvaluationDispatcherWorkflow,
    CheckAlertWorkflow,
    CleanupAlertChecksWorkflow,
    RunInvestigationSafetyNetWorkflow,
    ScheduleDueAlertChecksWorkflow,
)

WORKFLOWS = [
    ScheduleDueAlertChecksWorkflow,
    AlertEvaluationDispatcherWorkflow,
    CheckAlertWorkflow,
    RunInvestigationSafetyNetWorkflow,
    CleanupAlertChecksWorkflow,
]

ACTIVITIES = [
    retrieve_due_alerts,
    prepare_alert,
    evaluate_alert,
    notify_alert,
    run_investigation_safety_net,
    cleanup_alert_checks,
    enqueue_alert_checks,
]
