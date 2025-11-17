from posthog.temporal.messaging.realtime_cohort_calculation_workflow import (
    RealtimeCohortCalculationWorkflow,
    process_realtime_cohort_calculation_activity,
)
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    RealtimeCohortCalculationCoordinatorWorkflow,
    get_realtime_cohort_calculation_count_activity,
)

WORKFLOWS = [
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationCoordinatorWorkflow,
]
ACTIVITIES = [
    get_realtime_cohort_calculation_count_activity,
    process_realtime_cohort_calculation_activity,
]
