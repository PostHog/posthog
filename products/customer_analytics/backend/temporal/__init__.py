from products.customer_analytics.backend.temporal.account_track_rules import (
    AccountTrackRuleEvaluationWorkflow,
    account_track_rule_fail_run_activity,
    account_track_rule_process_batch_activity,
)
from products.customer_analytics.backend.temporal.calendar_sync import (
    CalendarSyncCoordinatorWorkflow,
    CalendarSyncWorkflow,
    calendar_sync_collect_integrations_activity,
    calendar_sync_integration_activity,
)

WORKFLOWS = [AccountTrackRuleEvaluationWorkflow, CalendarSyncCoordinatorWorkflow, CalendarSyncWorkflow]
ACTIVITIES = [
    account_track_rule_process_batch_activity,
    account_track_rule_fail_run_activity,
    calendar_sync_collect_integrations_activity,
    calendar_sync_integration_activity,
]
