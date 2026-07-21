"""Cross-team (fleet) reads for the data_modeling_ops internal API.

Pure DB aggregation — Temporal state comes in as arguments (see logic/schedule_truth.py)
so each request performs at most one namespace listing. All queries here are genuinely
cross-team: this backs a staff-only ops surface, not customer requests.
"""

import uuid
from typing import Any

from django.db.models import Count, Q

from products.data_modeling.backend.models import DAG, DataModelingJob, DataModelingJobStatus, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

# Bound fleet sweeps so one request cannot scan unbounded job history.
FAILING_SAVED_QUERY_CAP = 500
UNSCHEDULED_SCAN_CAP = 2000
FAILING_JOBS_SCAN_CAP = 10_000
RESOLVE_MATCH_CAP = 50


def modeling_team_ids() -> list[int]:
    """Teams with any data-modeling footprint: a saved query or a DAG."""
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    saved_query_teams = (
        DataWarehouseSavedQuery.objects.exclude(deleted=True)
        .exclude(team_id__isnull=True)
        .values_list("team_id", flat=True)
        .distinct()
    )
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    dag_teams = DAG.objects.exclude(team_id__isnull=True).values_list("team_id", flat=True).distinct()
    return sorted({*saved_query_teams, *dag_teams})


def team_activity_rows(team_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Per-team entity counts for the given teams."""
    rows: dict[int, dict[str, Any]] = {
        team_id: {
            "team_id": team_id,
            "saved_query_count": 0,
            "materialized_saved_query_count": 0,
            "failing_saved_query_count": 0,
            "saved_queries_with_sync_frequency_count": 0,
            "endpoint_origin_saved_query_count": 0,
            "dag_count": 0,
        }
        for team_id in team_ids
    }
    saved_query_counts = (
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        DataWarehouseSavedQuery.objects.filter(team_id__in=team_ids)
        .exclude(deleted=True)
        .values("team_id")
        .annotate(
            total=Count("id"),
            materialized=Count("id", filter=Q(is_materialized=True)),
            failing=Count("id", filter=Q(status=DataWarehouseSavedQuery.Status.FAILED)),
            with_sync_frequency=Count("id", filter=Q(sync_frequency_interval__isnull=False)),
            endpoint_origin=Count("id", filter=Q(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)),
        )
    )
    for entry in saved_query_counts:
        row = rows[entry["team_id"]]
        row["saved_query_count"] = entry["total"]
        row["materialized_saved_query_count"] = entry["materialized"]
        row["failing_saved_query_count"] = entry["failing"]
        row["saved_queries_with_sync_frequency_count"] = entry["with_sync_frequency"]
        row["endpoint_origin_saved_query_count"] = entry["endpoint_origin"]

    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    for entry in DAG.objects.filter(team_id__in=team_ids).values("team_id").annotate(total=Count("id")):
        rows[entry["team_id"]]["dag_count"] = entry["total"]
    return rows


def classify_migration(
    *,
    has_dags: bool,
    v2_flag_enabled: bool,
    v2_schedule_present: bool,
    sync_frequencies_remaining: int,
) -> str:
    """Label a team's position across the three migration switches (flag A, v2 schedule B,
    nulled sync_frequency_interval C)."""
    if not has_dags and not v2_schedule_present:
        return "no_dags"
    if v2_schedule_present:
        if not v2_flag_enabled:
            return "v2_scheduled_flag_excluded"
        if sync_frequencies_remaining > 0:
            return "v2_scheduled_cleanup_pending"
        return "fully_v2"
    if not v2_flag_enabled:
        return "v1_flag_excluded"
    return "not_migrated"


def dag_ids_by_team(team_ids: list[int]) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {team_id: [] for team_id in team_ids}
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    for team_id, dag_id in DAG.objects.filter(team_id__in=team_ids).values_list("team_id", "id"):
        result[team_id].append(str(dag_id))
    return result


def find_orphaned_schedules(schedules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Schedules whose owning entity no longer exists: v1 schedule id with no live saved
    query, v2 schedule id with no DAG. The read-only twin of
    delete_orphaned_saved_query_schedules, plus the execute-dag direction it lacks."""
    v1_ids = {s["schedule_id"] for s in schedules if s["kind"] == "v1_saved_query"}
    v2_ids = {s["schedule_id"] for s in schedules if s["kind"] == "v2_dag"}

    live_saved_query_ids = {
        str(pk)
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        for pk in DataWarehouseSavedQuery.objects.filter(id__in=_valid_uuids(v1_ids))
        .exclude(deleted=True)
        .values_list("id", flat=True)
    }
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    live_dag_ids = {str(pk) for pk in DAG.objects.filter(id__in=_valid_uuids(v2_ids)).values_list("id", flat=True)}

    orphaned = []
    for schedule in schedules:
        if schedule["kind"] == "v1_saved_query" and schedule["schedule_id"] not in live_saved_query_ids:
            orphaned.append(schedule)
        elif schedule["kind"] == "v2_dag" and schedule["schedule_id"] not in live_dag_ids:
            orphaned.append(schedule)
    return orphaned


def find_unscheduled_entities(schedules: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Materialized saved queries with no covering Temporal schedule — neither their own
    v1 schedule nor a v2 schedule on any DAG they have a node in. The scan is capped at
    UNSCHEDULED_SCAN_CAP rows; the second return value reports whether it was cut off."""
    v1_ids = {s["schedule_id"] for s in schedules if s["kind"] == "v1_saved_query"}
    v2_ids = {s["schedule_id"] for s in schedules if s["kind"] == "v2_dag"}

    materialized = list(
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        DataWarehouseSavedQuery.objects.filter(is_materialized=True)
        .exclude(deleted=True)
        .order_by("team_id", "name")
        .values("id", "team_id", "name", "is_materialized", "sync_frequency_interval", "last_run_at")[
            :UNSCHEDULED_SCAN_CAP
        ]
    )
    saved_query_ids = [entry["id"] for entry in materialized]
    node_dags: dict[uuid.UUID, list[str]] = {}
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    for saved_query_id, dag_id in Node.objects.filter(saved_query_id__in=saved_query_ids).values_list(
        "saved_query_id", "dag_id"
    ):
        node_dags.setdefault(saved_query_id, []).append(str(dag_id))

    unscheduled = []
    for entry in materialized:
        dag_ids = node_dags.get(entry["id"], [])
        if str(entry["id"]) in v1_ids or any(dag_id in v2_ids for dag_id in dag_ids):
            continue
        unscheduled.append(
            {
                "team_id": entry["team_id"],
                "saved_query_id": str(entry["id"]),
                "name": entry["name"],
                "is_materialized": entry["is_materialized"],
                "sync_frequency_interval": entry["sync_frequency_interval"],
                "last_run_at": entry["last_run_at"],
                "dag_ids": dag_ids,
            }
        )
    return unscheduled, len(materialized) == UNSCHEDULED_SCAN_CAP


def find_multi_dag_saved_queries() -> list[dict[str, Any]]:
    """Saved queries with nodes in more than one DAG — double-materialized every cycle."""
    duplicated = (
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        Node.objects.filter(saved_query_id__isnull=False)
        .values("saved_query_id")
        .annotate(dag_count=Count("dag_id", distinct=True))
        .filter(dag_count__gt=1)
    )
    saved_query_ids = [entry["saved_query_id"] for entry in duplicated]
    if not saved_query_ids:
        return []

    dags_by_saved_query: dict[uuid.UUID, list[dict[str, str]]] = {}
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    for node in Node.objects.filter(saved_query_id__in=saved_query_ids).select_related("dag").order_by("dag__name"):
        if node.saved_query_id is None:
            continue
        dags_by_saved_query.setdefault(node.saved_query_id, []).append(
            {"dag_id": str(node.dag_id), "dag_name": node.dag.name}
        )

    results = []
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    for saved_query in DataWarehouseSavedQuery.objects.filter(id__in=saved_query_ids).order_by("team_id", "name"):
        results.append(
            {
                "team_id": saved_query.team_id,
                "saved_query_id": str(saved_query.id),
                "name": saved_query.name,
                "is_materialized": saved_query.is_materialized,
                "dags": dags_by_saved_query.get(saved_query.id, []),
            }
        )
    return results


def find_duplicate_backing_tables() -> list[dict[str, Any]]:
    """Saved queries with more than one same-named DataWarehouseTable in their team —
    the orphaned-duplicate-backing-table regression class."""
    duplicated_names = (
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        DataWarehouseTable.objects.exclude(deleted=True)
        .values("team_id", "name")
        .annotate(table_count=Count("id"))
        .filter(table_count__gt=1)
    )
    pairs = {(entry["team_id"], entry["name"]) for entry in duplicated_names}
    if not pairs:
        return []

    name_filter = Q()
    for team_id, name in pairs:
        name_filter |= Q(team_id=team_id, name=name)
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    saved_queries = (
        DataWarehouseSavedQuery.objects.filter(name_filter).exclude(deleted=True).order_by("team_id", "name")
    )

    tables_by_pair: dict[tuple[int, str], list[DataWarehouseTable]] = {}
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    for table in DataWarehouseTable.objects.filter(name_filter).exclude(deleted=True).order_by("created_at"):
        tables_by_pair.setdefault((table.team_id, table.name), []).append(table)

    results = []
    for saved_query in saved_queries:
        results.append(
            {
                "team_id": saved_query.team_id,
                "saved_query_id": str(saved_query.id),
                "name": saved_query.name,
                "linked_table_id": str(saved_query.table_id) if saved_query.table_id else None,
                "tables": tables_by_pair.get((saved_query.team_id, saved_query.name), []),
            }
        )
    return results


def failing_saved_query_rows() -> list[dict[str, Any]]:
    """Saved queries currently in FAILED status, with per-engine consecutive-failure
    counts derived from recent job history (jobs are the primary failure signal; the
    engine split keeps duck-shadow jobs from polluting the serving engine's count)."""
    failing = list(
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        DataWarehouseSavedQuery.objects.filter(status=DataWarehouseSavedQuery.Status.FAILED)
        .exclude(deleted=True)
        .order_by("team_id", "name")[:FAILING_SAVED_QUERY_CAP]
    )
    if not failing:
        return []

    jobs = (
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        DataModelingJob.objects.filter(saved_query_id__in=[saved_query.id for saved_query in failing])
        .order_by("-created_at")
        .values("saved_query_id", "engine", "status", "error", "created_at")[:FAILING_JOBS_SCAN_CAP]
    )
    # Jobs arrive newest-first; a per-engine streak stops counting at that engine's
    # first non-FAILED job.
    consecutive: dict[uuid.UUID, dict[str, int]] = {}
    streak_open: dict[tuple[uuid.UUID, str], bool] = {}
    last_failed_at: dict[uuid.UUID, Any] = {}
    for job in jobs:
        key = (job["saved_query_id"], job["engine"])
        if job["status"] == DataModelingJobStatus.FAILED:
            if streak_open.setdefault(key, True):
                per_engine = consecutive.setdefault(job["saved_query_id"], {})
                per_engine[job["engine"]] = per_engine.get(job["engine"], 0) + 1
            last_failed_at.setdefault(job["saved_query_id"], job["created_at"])
        elif job["status"] != DataModelingJobStatus.RUNNING:
            streak_open[key] = False

    node_context: dict[uuid.UUID, list[dict[str, Any]]] = {}
    # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
    for node in Node.objects.filter(saved_query_id__in=[saved_query.id for saved_query in failing]):
        if node.saved_query_id is None:
            continue
        node_context.setdefault(node.saved_query_id, []).append(
            {
                "node_id": str(node.id),
                "dag_id": str(node.dag_id),
                "suspended": (node.properties or {}).get("system", {}).get("suspended"),
            }
        )

    rows = []
    for saved_query in failing:
        rows.append(
            {
                "team_id": saved_query.team_id,
                "saved_query_id": str(saved_query.id),
                "name": saved_query.name,
                "latest_error": saved_query.latest_error,
                "last_run_at": saved_query.last_run_at,
                "last_failed_job_at": last_failed_at.get(saved_query.id),
                "consecutive_failures_by_engine": consecutive.get(saved_query.id, {}),
                "nodes": node_context.get(saved_query.id, []),
            }
        )
    return rows


def group_failing_by_schedule(rows: list[dict[str, Any]], schedules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group failing saved queries under the Temporal schedule that covers them: their own
    v1 schedule, a v2 schedule on one of their DAGs, or an 'unscheduled' bucket."""
    by_id = {s["schedule_id"]: s for s in schedules}
    groups: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    for row in rows:
        schedule = by_id.get(row["saved_query_id"])
        if schedule is None:
            for node in row["nodes"]:
                dag_schedule = by_id.get(node["dag_id"])
                if dag_schedule is not None and dag_schedule["kind"] == "v2_dag":
                    schedule = dag_schedule
                    break
        schedule_id = schedule["schedule_id"] if schedule else None
        # Unscheduled rows bucket per team so one group never mixes teams.
        group = groups.setdefault(
            (schedule_id, None if schedule_id else row["team_id"]),
            {
                "schedule_id": schedule_id,
                "schedule_kind": schedule["kind"] if schedule else "none",
                "paused": schedule["paused"] if schedule else None,
                "team_id": row["team_id"],
                "affected_saved_queries": [],
            },
        )
        group["affected_saved_queries"].append(row)
    return sorted(groups.values(), key=lambda group: (group["schedule_id"] is None, str(group["schedule_id"])))


def resolve_entity(kind: str, query: str) -> list[dict[str, Any]]:
    """Typed search across all teams for data_modeling entities. Returns match dicts of
    {kind, team_id, id, name, detail}; empty when nothing matches."""
    if kind == "saved_query":
        return _resolve_saved_query(query)
    if kind == "dag":
        return _resolve_dag(query)
    if kind == "node":
        return _resolve_node(query)
    if kind == "job":
        return _resolve_job(query)
    if kind == "schedule":
        return _resolve_saved_query(query) + _resolve_dag(query)
    if kind == "workflow":
        return _resolve_workflow(query)
    if kind == "name":
        return _resolve_name(query)
    raise ValueError(f"Unknown kind: {kind}")


def _valid_uuids(values: set[str] | list[str]) -> list[str]:
    valid = []
    for value in values:
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError, TypeError):
            continue
        valid.append(value)
    return valid


def _resolve_saved_query(query: str) -> list[dict[str, Any]]:
    if not _valid_uuids([query]):
        return []
    return [
        {
            "kind": "saved_query",
            "team_id": saved_query.team_id,
            "id": str(saved_query.id),
            "name": saved_query.name,
            "detail": {"deleted": bool(saved_query.deleted), "status": saved_query.status},
        }
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        for saved_query in DataWarehouseSavedQuery.objects.filter(id=query)
    ]


def _resolve_dag(query: str) -> list[dict[str, Any]]:
    if not _valid_uuids([query]):
        return []
    return [
        {
            "kind": "dag",
            "team_id": dag.team_id,
            "id": str(dag.id),
            "name": dag.name,
            "detail": {},
        }
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        for dag in DAG.objects.filter(id=query)
    ]


def _resolve_node(query: str) -> list[dict[str, Any]]:
    if not _valid_uuids([query]):
        return []
    return [
        {
            "kind": "node",
            "team_id": node.team_id,
            "id": str(node.id),
            "name": node.name,
            "detail": {
                "dag_id": str(node.dag_id),
                "saved_query_id": str(node.saved_query_id) if node.saved_query_id else None,
            },
        }
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        for node in Node.objects.filter(id=query)
    ]


def _resolve_job(query: str) -> list[dict[str, Any]]:
    if not _valid_uuids([query]):
        return []
    return [
        {
            "kind": "job",
            "team_id": job.team_id,
            "id": str(job.id),
            "name": job.workflow_id or "",
            "detail": {
                "saved_query_id": str(job.saved_query_id) if job.saved_query_id else None,
                "status": job.status,
                "engine": job.engine,
            },
        }
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        for job in DataModelingJob.objects.filter(id=query)
    ]


def _resolve_workflow(query: str) -> list[dict[str, Any]]:
    jobs = (
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        DataModelingJob.objects.filter(Q(workflow_id=query) | Q(parent_workflow_id=query)).order_by("-created_at")[
            :RESOLVE_MATCH_CAP
        ]
    )
    return [
        {
            "kind": "job",
            "team_id": job.team_id,
            "id": str(job.id),
            "name": job.workflow_id or "",
            "detail": {
                "saved_query_id": str(job.saved_query_id) if job.saved_query_id else None,
                "status": job.status,
                "engine": job.engine,
            },
        }
        for job in jobs
    ]


def _resolve_name(query: str) -> list[dict[str, Any]]:
    matches = (
        # nosemgrep: idor-lookup-without-team (staff-only fleet endpoint aggregates all teams)
        DataWarehouseSavedQuery.objects.filter(name__icontains=query)
        .exclude(deleted=True)
        .order_by("name")[:RESOLVE_MATCH_CAP]
    )
    results = [
        {
            "kind": "saved_query",
            "team_id": saved_query.team_id,
            "id": str(saved_query.id),
            "name": saved_query.name,
            "detail": {"status": saved_query.status, "is_materialized": saved_query.is_materialized},
        }
        for saved_query in matches
    ]
    return sorted(results, key=lambda match: (match["name"].lower() != query.lower(), match["name"]))
