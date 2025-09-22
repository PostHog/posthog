from posthog.temporal.messaging.behavioral_cohorts_workflow import (
    BehavioralCohortsWorkflow,
    get_unique_conditions_page_activity,
    process_condition_batch_activity,
)

WORKFLOWS = [BehavioralCohortsWorkflow]
ACTIVITIES = [
    get_unique_conditions_page_activity,
    process_condition_batch_activity,
]
