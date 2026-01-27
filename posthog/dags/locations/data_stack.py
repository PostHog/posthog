import dagster

from posthog.dags import events_backfill_to_ducklake

from products.data_warehouse.dags import managed_viewset_sync

from . import resources

defs = dagster.Definitions(
    assets=[
        events_backfill_to_ducklake.events_ducklake_backfill,
    ],
    jobs=[
        managed_viewset_sync.sync_managed_viewsets_job,
        events_backfill_to_ducklake.events_ducklake_backfill_job,
    ],
    resources=resources,
)
