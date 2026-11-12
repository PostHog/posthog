"""Query-result warnings for materialized views that fall behind their refresh schedule.

A query that reads a materialized view reads the stored table, not the view's sources, so it
cannot see that the stored table is old. These warnings ride the same `warnings` list as
warehouse source sync warnings, which every query surface (the UI, PostHog AI, MCP) already shows.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db.models import OuterRef, Subquery

import humanize

from posthog.schema import DataWarehouseSyncWarning

from posthog.utils import ensure_utc

from products.data_modeling.backend.logic.freshness import humanize_cadence
from products.data_modeling.backend.logic.node_frequency import scheduled_cadences_by_node
from products.data_modeling.backend.models import DataModelingJob, DataModelingJobEngine, DataModelingJobStatus
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node

# Matches the warehouse source rule in products/data_warehouse/backend/sync_status.py, so a view
# and a source table read as late at the same point relative to their cadence.
STALE_MULTIPLIER = 2

VIEW_STATUS_STALE = "Stale"

# Every query that reads a materialized view needs its DAG's cadences, and building them reads the
# whole DAG. A target change can take this long to move the warning threshold.
CADENCE_CACHE_TTL_SECONDS = 300


def view_freshness_warnings(
    team_id: int, saved_query_ids: Iterable[str], *, now: datetime
) -> dict[str, DataWarehouseSyncWarning]:
    """Warnings keyed by saved query id, for each materialized view that is late or failed its latest refresh.

    Late means older than twice its cadence. A view with no successful materialization gets no
    warning, because no stored result exists to describe.
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
    cadences = _scheduled_cadences(team_id, ids)

    warnings: dict[str, DataWarehouseSyncWarning] = {}
    for view in views:
        view_id = str(view.pk)
        # v2 teams keep the cadence on the DAG and leave the saved query's interval NULL.
        interval = cadences.get(view_id) or view.sync_frequency_interval
        # The v2 DAG records success on DataModelingJob and never writes saved_query.last_run_at.
        candidates = [ts for ts in (view.latest_success_at, view.last_run_at) if ts is not None]
        if not candidates:
            continue
        materialized_at = ensure_utc(max(candidates))
        late = interval is not None and now - materialized_at > interval * STALE_MULTIPLIER
        failed = view.latest_attempt_status == DataModelingJobStatus.FAILED
        if not late and not failed:
            continue

        ago = humanize.naturaltime(now - materialized_at)
        status: str
        if failed:
            status, message = DataModelingJobStatus.FAILED.value, _failed_view_message(view.name, ago=ago)
        elif interval is not None:
            status, message = (
                VIEW_STATUS_STALE,
                _stale_view_message(view.name, ago=ago, cadence=humanize_cadence(interval)),
            )
        else:
            continue
        warnings[view_id] = DataWarehouseSyncWarning(
            table_name=view.name,
            schema_name=view.name,
            source_type=f"materialized view {view.name}",
            source_id=None,
            status=status,
            message=message,
            # A failed refresh inside the window still serves current data, so "out of date" surfaces skip it.
            data_is_current=interval is not None and not late,
        )
    return warnings


def _scheduled_cadences(team_id: int, saved_query_ids: list[str]) -> dict[str, timedelta]:
    """The cadence the scheduler refreshes each view at, keyed by saved query id.

    This includes a cadence a view inherits from the nodes that read it, which no declared target
    shows. A view on several nodes takes the finest cadence, since that is how often it refreshes.
    """
    nodes = list(
        Node.objects.filter(team_id=team_id, saved_query_id__in=saved_query_ids).only("id", "dag_id", "saved_query_id")
    )
    if not nodes:
        return {}
    by_node = _cached_cadences_by_node(team_id, {str(node.dag_id) for node in nodes})
    finest: dict[str, timedelta] = {}
    for node in nodes:
        cadence = by_node.get(str(node.id))
        query_id = str(node.saved_query_id)
        if cadence is not None and (query_id not in finest or cadence < finest[query_id]):
            finest[query_id] = cadence
    return finest


def _cached_cadences_by_node(team_id: int, dag_ids: set[str]) -> dict[str, timedelta | None]:
    keys = {dag_id: f"data_modeling:view_freshness:cadences:{team_id}:{dag_id}" for dag_id in dag_ids}
    cached: dict[str, dict[str, timedelta | None]] = cache.get_many(list(keys.values()))
    by_node: dict[str, timedelta | None] = {}
    for dag_id, key in keys.items():
        cadences = cached.get(key)
        if cadences is None:
            cadences = scheduled_cadences_by_node(team_id, [dag_id])
            cache.set(key, cadences, CADENCE_CACHE_TTL_SECONDS)
        by_node.update(cadences)
    return by_node


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
