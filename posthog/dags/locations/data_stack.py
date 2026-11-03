import dagster

from posthog.dags import events_backfill_to_duckling

from products.data_modeling.backend.facade.dags import job_usage
from products.data_warehouse.backend.facade.dags import managed_viewset_sync
from products.managed_warehouse.backend.facade.dags import groups_backfill

from . import loggers, resources

defs = dagster.Definitions(
    assets=[
        groups_backfill.duckling_groups_backfill,
        events_backfill_to_duckling.duckling_events_backfill,
        events_backfill_to_duckling.duckling_persons_backfill,
    ],
    jobs=[
        job_usage.model_job_usage_job,
        groups_backfill.duckling_groups_backfill_job,
        managed_viewset_sync.sync_managed_viewsets_job,
        events_backfill_to_duckling.duckling_events_backfill_job,
        events_backfill_to_duckling.duckling_persons_backfill_job,
    ],
    schedules=[job_usage.model_job_usage_schedule],
    sensors=[
        groups_backfill.duckling_groups_full_backfill_sensor,
        groups_backfill.duckling_groups_daily_backfill_sensor,
        events_backfill_to_duckling.duckling_events_daily_backfill_sensor,
        events_backfill_to_duckling.duckling_events_full_backfill_sensor,
        events_backfill_to_duckling.duckling_persons_daily_backfill_sensor,
        events_backfill_to_duckling.duckling_persons_full_backfill_sensor,
    ],
    loggers=loggers,
    resources=resources,
)
