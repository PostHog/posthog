"""Read-side freshness derivation for saved queries.

Kept free of workflow/temporal imports so facade consumers can resolve it during
django.setup() without pulling the materialization dispatch stack (and its circular
import back into products.endpoints).
"""

from datetime import datetime

from products.data_modeling.backend.models import DataModelingJob, DataModelingJobEngine, DataModelingJobStatus
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


def saved_query_materialized_at(saved_query: DataWarehouseSavedQuery) -> datetime | None:
    """Latest successful materialization time for the saved query.

    The v2 DAG records success on DataModelingJob but never writes saved_query.last_run_at, so
    read freshness from the newest Completed clickhouse job and fall back to the frozen v1 field.
    """
    job_last_run_at = (
        DataModelingJob.objects.filter(
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
