from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
    sample_uuid_boundaries_activity,
)
from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesWorkflow,
    backfill_precalculated_person_properties_activity,
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
    BackfillPrecalculatedPersonPropertiesWorkflow,
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationCoordinatorWorkflow,
]
ACTIVITIES = [
    sample_uuid_boundaries_activity,
    get_realtime_cohort_calculation_count_activity,
    backfill_precalculated_person_properties_activity,
    process_realtime_cohort_calculation_activity,
]
