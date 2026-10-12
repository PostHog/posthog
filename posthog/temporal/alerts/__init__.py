from posthog.temporal.alerts.activities import (
    admit_alert_evaluations,
    cleanup_alert_checks,
    evaluate_alert,
    notify_alert,
    prepare_alert,
    record_failed_evaluation,
    release_alert_evaluation_slots,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.workflows import (
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
]

# CheckAlertWorkflow routes an AI detector's evaluation to the AI task queue, because only
# that worker holds the model provider credentials.
AI_QUEUE_ACTIVITIES = [evaluate_alert]

ACTIVITIES = [
    retrieve_due_alerts,
    admit_alert_evaluations,
    release_alert_evaluation_slots,
    prepare_alert,
    evaluate_alert,
    notify_alert,
    record_failed_evaluation,
    run_investigation_safety_net,
    cleanup_alert_checks,
]
