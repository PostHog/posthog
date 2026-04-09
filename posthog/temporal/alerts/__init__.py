from posthog.temporal.alerts.activities import (
    enumerate_due_alerts_activity,
    evaluate_alert_activity,
    notify_alert_activity,
    prepare_alert_activity,
)
from posthog.temporal.alerts.workflows import CheckAlertWorkflow, ScheduleAllAlertChecksWorkflow

WORKFLOWS = [ScheduleAllAlertChecksWorkflow, CheckAlertWorkflow]

ACTIVITIES = [
    enumerate_due_alerts_activity,
    prepare_alert_activity,
    evaluate_alert_activity,
    notify_alert_activity,
]
