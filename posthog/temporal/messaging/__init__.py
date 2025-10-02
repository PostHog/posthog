from posthog.temporal.messaging.behavioral_cohorts_workflow import (
    BehavioralCohortsWorkflow,
    get_unique_conditions_page_activity,
    process_condition_batch_activity,
)
from posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator import (
    BehavioralCohortsCoordinatorWorkflow,
    get_conditions_count_activity,
)

WORKFLOWS = [
    BehavioralCohortsWorkflow,
    BehavioralCohortsCoordinatorWorkflow,
]
ACTIVITIES = [
    get_unique_conditions_page_activity,
    process_condition_batch_activity,
    get_conditions_count_activity,
]
