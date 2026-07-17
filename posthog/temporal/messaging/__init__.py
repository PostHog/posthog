from posthog.temporal.messaging.backfill_precalculated_events_coordinator_workflow import (
    BackfillPrecalculatedEventsCoordinatorWorkflow,
    check_day_already_backfilled_activity,
)
from posthog.temporal.messaging.backfill_precalculated_events_workflow import (
    BackfillPrecalculatedEventsWorkflow,
    backfill_precalculated_events_activity,
)
from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
    get_person_id_ranges_page_activity,
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
from posthog.temporal.messaging.reconcile_precalculated_data_workflow import (
    ReconcilePrecalculatedEventsWorkflow,
    get_reconciliation_run_config_activity,
    get_reconciliation_team_ids_activity,
    reconcile_team_precalculated_events_activity,
    reconcile_team_precalculated_person_properties_activity,
)

WORKFLOWS = [
    BackfillPrecalculatedEventsWorkflow,
    BackfillPrecalculatedEventsCoordinatorWorkflow,
    BackfillPrecalculatedPersonPropertiesWorkflow,
    BackfillPrecalculatedPersonPropertiesCoordinatorWorkflow,
    RealtimeCohortCalculationWorkflow,
    RealtimeCohortCalculationCoordinatorWorkflow,
    ReconcilePrecalculatedEventsWorkflow,
]
ACTIVITIES = [
    backfill_precalculated_events_activity,
    check_day_already_backfilled_activity,
    get_realtime_cohort_selection_activity,
    get_query_percentile_thresholds_activity,
    backfill_precalculated_person_properties_activity,
    get_person_id_ranges_page_activity,
    process_realtime_cohort_calculation_activity,
    get_reconciliation_team_ids_activity,
    get_reconciliation_run_config_activity,
    reconcile_team_precalculated_events_activity,
    reconcile_team_precalculated_person_properties_activity,
]
