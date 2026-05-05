from posthog.temporal.alerts.activities import (
    evaluate_alert,
    notify_alert,
    prepare_alert,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.workflows import (
    CheckAlertWorkflow,
    RunInvestigationSafetyNetWorkflow,
    ScheduleDueAlertChecksWorkflow,
)

WORKFLOWS = [
    ScheduleDueAlertChecksWorkflow,
    CheckAlertWorkflow,
    RunInvestigationSafetyNetWorkflow,
]

ACTIVITIES = [
    retrieve_due_alerts,
    prepare_alert,
    evaluate_alert,
    notify_alert,
    run_investigation_safety_net,
]
