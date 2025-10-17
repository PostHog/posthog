from posthog.temporal.messaging.actions_workflow import ActionsWorkflow, process_actions_activity
from posthog.temporal.messaging.actions_workflow_coordinator import (
    ActionsCoordinatorWorkflow,
    get_actions_count_activity,
)
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
    ActionsWorkflow,
    ActionsCoordinatorWorkflow,
    BehavioralCohortsWorkflow,
    BehavioralCohortsCoordinatorWorkflow,
]
ACTIVITIES = [
    get_actions_count_activity,
    get_conditions_count_activity,
    get_unique_conditions_page_activity,
    process_actions_activity,
    process_condition_batch_activity,
    check_running_workflows_activity,
]
