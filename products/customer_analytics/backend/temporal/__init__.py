from products.customer_analytics.backend.temporal.account_track_rules import (
    AccountTrackRuleCoordinatorWorkflow,
    AccountTrackRuleEvaluationWorkflow,
    account_track_rule_collect_configs_activity,
    account_track_rule_create_scheduled_run_activity,
    account_track_rule_fail_run_activity,
    account_track_rule_observe_coordinator_activity,
    account_track_rule_process_batch_activity,
)
from products.customer_analytics.backend.temporal.calendar_sync import (
    CalendarSyncCoordinatorWorkflow,
    CalendarSyncWorkflow,
    calendar_sync_collect_integrations_activity,
    calendar_sync_integration_activity,
)

WORKFLOWS = [
    AccountTrackRuleCoordinatorWorkflow,
    AccountTrackRuleEvaluationWorkflow,
    CalendarSyncCoordinatorWorkflow,
    CalendarSyncWorkflow,
]
ACTIVITIES = [
    account_track_rule_collect_configs_activity,
    account_track_rule_create_scheduled_run_activity,
    account_track_rule_fail_run_activity,
    account_track_rule_observe_coordinator_activity,
    account_track_rule_process_batch_activity,
    calendar_sync_collect_integrations_activity,
    calendar_sync_integration_activity,
]
