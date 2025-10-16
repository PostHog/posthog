from posthog.temporal.messaging.behavioral_cohorts_workflow import (
    BehavioralCohortsWorkflow,
    get_unique_conditions_page_activity,
    process_condition_batch_activity,
)
from posthog.temporal.messaging.behavioral_cohorts_workflow_coordinator import (
    BehavioralCohortsCoordinatorWorkflow,
    check_running_workflows_activity,
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
    check_running_workflows_activity,
]
