import dagster

from posthog.dags import events_backfill_to_duckling

from products.data_modeling.backend.facade.dags import saved_query_demand
from products.data_warehouse.backend.facade.dags import managed_viewset_sync

from . import loggers, resources

defs = dagster.Definitions(
    assets=[
        events_backfill_to_duckling.duckling_events_backfill,
        events_backfill_to_duckling.duckling_persons_backfill,
    ],
    jobs=[
        managed_viewset_sync.sync_managed_viewsets_job,
        saved_query_demand.record_saved_query_demand_job,
        events_backfill_to_duckling.duckling_events_backfill_job,
        events_backfill_to_duckling.duckling_persons_backfill_job,
    ],
    schedules=[saved_query_demand.record_saved_query_demand_schedule],
    sensors=[
        events_backfill_to_duckling.duckling_events_daily_backfill_sensor,
        events_backfill_to_duckling.duckling_events_full_backfill_sensor,
        events_backfill_to_duckling.duckling_persons_daily_backfill_sensor,
        events_backfill_to_duckling.duckling_persons_full_backfill_sensor,
    ],
    loggers=loggers,
    resources=resources,
)
