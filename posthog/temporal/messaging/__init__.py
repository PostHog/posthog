from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
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
    get_query_percentile_thresholds_activity,
    get_realtime_cohort_selection_activity,
)

WORKFLOWS = [
    BackfillPrecalculatedPersonPropertiesWorkflow,
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationCoordinatorWorkflow,
]
ACTIVITIES = [
    get_realtime_cohort_selection_activity,
    get_query_percentile_thresholds_activity,
    backfill_precalculated_person_properties_activity,
    process_realtime_cohort_calculation_activity,
]
