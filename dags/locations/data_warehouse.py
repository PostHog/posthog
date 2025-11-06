import dagster

from dags import managed_viewset_sync

from . import resources

defs = dagster.Definitions(
    jobs=[
        managed_viewset_sync.sync_managed_viewsets_job,
    ],
    resources=resources,
)
