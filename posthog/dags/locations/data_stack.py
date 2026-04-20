import dagster

from posthog.dags import events_backfill_to_ducklake, events_backfill_to_duckling

from products.data_warehouse.dags import managed_viewset_sync

from . import resources

defs = dagster.Definitions(
    assets=[
        events_backfill_to_ducklake.events_ducklake_backfill,
        events_backfill_to_duckling.duckling_events_backfill,
        events_backfill_to_duckling.duckling_persons_backfill,
    ],
    jobs=[
        managed_viewset_sync.sync_managed_viewsets_job,
        events_backfill_to_ducklake.events_ducklake_backfill_job,
        events_backfill_to_duckling.duckling_events_backfill_job,
        events_backfill_to_duckling.duckling_persons_backfill_job,
    ],
    sensors=[
        events_backfill_to_duckling.duckling_events_daily_backfill_sensor,
        events_backfill_to_duckling.duckling_events_full_backfill_sensor,
        events_backfill_to_duckling.duckling_persons_daily_backfill_sensor,
        events_backfill_to_duckling.duckling_persons_full_backfill_sensor,
    ],
    resources=resources,
)
