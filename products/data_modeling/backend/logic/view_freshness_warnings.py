"""Query-result warnings for materialized views that fall behind their refresh schedule.

A query that reads a materialized view reads the stored table, not the view's sources, so it
cannot see that the stored table is old. These warnings ride the same `warnings` list as
warehouse source sync warnings, which every query surface (the UI, PostHog AI, MCP) already shows.
"""

from collections.abc import Iterable
from datetime import datetime

from django.db.models import OuterRef, Subquery

import humanize

from posthog.schema import DataWarehouseSyncWarning

from posthog.utils import ensure_utc

from products.data_modeling.backend.logic.freshness import humanize_cadence
from products.data_modeling.backend.logic.node_frequency import declared_targets_by_saved_query
from products.data_modeling.backend.models import DataModelingJob, DataModelingJobEngine, DataModelingJobStatus
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

# Matches the warehouse source rule in products/data_warehouse/backend/sync_status.py, so a view
# and a source table read as late at the same point relative to their cadence.
STALE_MULTIPLIER = 2

VIEW_STATUS_STALE = "Stale"


def view_freshness_warnings(
    team_id: int, saved_query_ids: Iterable[str], *, now: datetime
) -> dict[str, DataWarehouseSyncWarning]:
    """Warnings keyed by saved query id, for each materialized view older than twice its cadence.

    A view with no cadence or no successful materialization gets no warning, because nothing
    says when it should have refreshed.
    """
    ids = sorted(set(saved_query_ids))
    if not ids:
        return {}

    clickhouse_jobs = DataModelingJob.objects.filter(
        team_id=team_id, saved_query_id=OuterRef("pk"), engine=DataModelingJobEngine.CLICKHOUSE
    ).order_by("-last_run_at")
    views = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id__in=ids)
        .exclude(deleted=True)
        .annotate(
            latest_success_at=Subquery(
                clickhouse_jobs.filter(status=DataModelingJobStatus.COMPLETED).values("last_run_at")[:1]
            ),
            latest_attempt_status=Subquery(clickhouse_jobs.values("status")[:1]),
        )
        .only("id", "name", "last_run_at", "sync_frequency_interval")
    )
    targets = declared_targets_by_saved_query(team_id, ids)

    warnings: dict[str, DataWarehouseSyncWarning] = {}
    for view in views:
        view_id = str(view.pk)
        # v2 teams keep the cadence on the DAG node and leave the saved query's interval NULL.
        interval = targets.get(view_id) or view.sync_frequency_interval
        # The v2 DAG records success on DataModelingJob and never writes saved_query.last_run_at.
        candidates = [ts for ts in (view.latest_success_at, view.last_run_at) if ts is not None]
        if interval is None or not candidates:
            continue
        materialized_at = ensure_utc(max(candidates))
        if now - materialized_at <= interval * STALE_MULTIPLIER:
            continue

        ago = humanize.naturaltime(now - materialized_at)
        status: str
        if view.latest_attempt_status == DataModelingJobStatus.FAILED:
            status, message = DataModelingJobStatus.FAILED.value, _failed_view_message(view.name, ago=ago)
        else:
            status, message = (
                VIEW_STATUS_STALE,
                _stale_view_message(view.name, ago=ago, cadence=humanize_cadence(interval)),
            )
        warnings[view_id] = DataWarehouseSyncWarning(
            table_name=view.name,
            schema_name=view.name,
            source_type=f"materialized view {view.name}",
            source_id=None,
            status=status,
            message=message,
            data_is_current=False,
        )
    return warnings


def _stale_view_message(view_name: str, *, ago: str, cadence: str) -> str:
    return (
        f"Materialized view `{view_name}` last refreshed {ago}, but it is set to refresh every {cadence}. "
        "Results may be out of date."
    )


def _failed_view_message(view_name: str, *, ago: str) -> str:
    return (
        f"The latest refresh of materialized view `{view_name}` failed. "
        f"Results reflect the last successful refresh from {ago}. Check the view's run history for details."
    )
