"""Read-side freshness derivation for saved queries.

Kept free of workflow/temporal imports so facade consumers can resolve it during
django.setup() without pulling the materialization dispatch stack (and its circular
import back into products.endpoints).
"""

from datetime import datetime, timedelta

from django.utils import timezone

from products.data_modeling.backend.models import DataModelingJob, DataModelingJobEngine, DataModelingJobStatus
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


def saved_query_materialized_at(saved_query: DataWarehouseSavedQuery) -> datetime | None:
    """Latest successful materialization time for the saved query.

    The v2 DAG records success on DataModelingJob but never writes saved_query.last_run_at, so
    read freshness from the newest Completed clickhouse job and fall back to the frozen v1 field.
    """
    prefetched_jobs = getattr(saved_query, "prefetched_latest_completed_jobs", None)
    job_last_run_at = (
        (prefetched_jobs[0].last_run_at if prefetched_jobs else None)
        if prefetched_jobs is not None
        else DataModelingJob.objects.filter(
            team_id=saved_query.team_id,
            saved_query_id=saved_query.id,
            status=DataModelingJobStatus.COMPLETED,
            engine=DataModelingJobEngine.CLICKHOUSE,
        )
        .order_by("-last_run_at")
        .values_list("last_run_at", flat=True)
        .first()
    )
    candidates = [ts for ts in (job_last_run_at, saved_query.last_run_at) if ts is not None]
    return max(candidates) if candidates else None


def latest_saved_query_materialization_job(saved_query: DataWarehouseSavedQuery) -> DataModelingJob | None:
    """Return the latest ClickHouse materialization attempt recorded by the v2 workflow."""
    prefetched_jobs = getattr(saved_query, "prefetched_latest_jobs", None)
    if prefetched_jobs is not None:
        return prefetched_jobs[0] if prefetched_jobs else None
    return (
        DataModelingJob.objects.filter(
            team_id=saved_query.team_id,
            saved_query_id=saved_query.id,
            engine=DataModelingJobEngine.CLICKHOUSE,
        )
        .order_by("-last_run_at")
        .first()
    )


def is_materialization_fresh(materialized_at: datetime | None, freshness_seconds: int | None) -> bool:
    """Whether a successful materialization is still within its serving window."""
    if materialized_at is None:
        return False
    if not freshness_seconds:
        return True
    return timezone.now() < materialized_at + timedelta(seconds=freshness_seconds)
