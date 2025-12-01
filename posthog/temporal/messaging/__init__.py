from posthog.temporal.messaging.precalculate_person_properties_workflow import (
    PrecalculatePersonPropertiesWorkflow,
    precalculate_person_properties_activity,
)
from posthog.temporal.messaging.precalculate_person_properties_workflow_coordinator import (
    PrecalculatePersonPropertiesCoordinatorWorkflow,
    get_person_count_activity,
)
from posthog.temporal.messaging.realtime_cohort_calculation_workflow import (
    RealtimeCohortCalculationWorkflow,
    process_realtime_cohort_calculation_activity,
)
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    RealtimeCohortCalculationCoordinatorWorkflow,
    get_realtime_cohort_calculation_count_activity,
)

WORKFLOWS = [
    PrecalculatePersonPropertiesWorkflow,
    PrecalculatePersonPropertiesCoordinatorWorkflow,
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationCoordinatorWorkflow,
]
ACTIVITIES = [
    get_person_count_activity,
    get_realtime_cohort_calculation_count_activity,
    precalculate_person_properties_activity,
    process_realtime_cohort_calculation_activity,
]
