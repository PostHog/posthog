from posthog.temporal.alerts.activities import (
    cleanup_alert_checks,
    evaluate_alert,
    notify_alert,
    prepare_alert,
    retrieve_due_alerts,
    run_investigation_safety_net,
)
from posthog.temporal.alerts.posthog_code_investigation import (
    PostHogCodeInvestigationWorkflow,
    cancel_posthog_code_investigation,
    create_posthog_code_investigation_task,
    finalize_posthog_code_investigation,
    get_investigation_run_state,
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
    PostHogCodeInvestigationWorkflow,
]

ACTIVITIES = [
    retrieve_due_alerts,
    prepare_alert,
    evaluate_alert,
    notify_alert,
    run_investigation_safety_net,
    cleanup_alert_checks,
    create_posthog_code_investigation_task,
    get_investigation_run_state,
    finalize_posthog_code_investigation,
    cancel_posthog_code_investigation,
]
