import re
import datetime as dt
from uuid import UUID

from django.db import transaction

from posthog.sync import database_sync_to_async_pool

from products.data_modeling.backend.facade.api import (
    clear_node_suspension,
    is_node_suspended,
    mark_node_suspended,
    query_fingerprint,
    suspension_reset_at,
)
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
    Node,
)

# Suspension state lives in products/data_modeling/backend/logic/node_suspension.py, alongside the
# API and DAG-sync paths that clear it. Re-exported so the activities keep importing from here.
__all__ = [
    "CONSECUTIVE_FAILURES_TO_SUSPEND",
    "clear_node_suspension",
    "clear_node_suspension_for_engine",
    "is_node_suspended",
    "mark_node_suspended",
    "maybe_suspend_node_for_engine",
    "strip_hostname_from_error",
    "update_node_system_properties",
]

# Consecutive failed jobs (per engine) before a node is suspended from future DAG runs.
CONSECUTIVE_FAILURES_TO_SUSPEND = 5

# Regex patterns for stripping hostnames from ClickHouse error messages
# Matches patterns like: "(from chi-xxx.svc.cluster.local:9000)" or "(from 10.0.0.1:9000)"
_HOSTNAME_FROM_PATTERN = re.compile(r"\(from\s+[^\s\)]+:\d+\)")
# Matches patterns like: "Received from chi-xxx.svc.cluster.local:9000" or "Received from 10.0.0.1:9000"
_HOSTNAME_RECEIVED_PATTERN = re.compile(r"Received from\s+[^\s:]+:\d+")


def strip_hostname_from_error(error_message: str) -> str:
    """Strip hostname/IP information from error messages to avoid exposing internal infrastructure.

    This is used to sanitize error messages before showing them to users, while the original
    error message with the hostname should still be logged internally for debugging.

    Common patterns stripped:
    - "(from chi-xxx.svc.cluster.local:9000)" -> "(from [host])"
    - "Received from chi-xxx.svc.cluster.local:9000" -> "Received from [host]"
    """
    result = _HOSTNAME_FROM_PATTERN.sub("(from [host])", error_message)
    result = _HOSTNAME_RECEIVED_PATTERN.sub("Received from [host]", result)
    return result


def update_node_system_properties(
    node: Node,
    *,
    status: str,
    job_id: str,
    rows: int | None = None,
    duration_seconds: float | None = None,
    error: str | None = None,
) -> None:
    properties: dict = node.properties or {}
    system = properties.get("system", {})

    system["last_run_at"] = dt.datetime.now(dt.UTC).isoformat()
    system["last_run_status"] = status
    system["last_run_job_id"] = job_id
    if rows is not None:
        system["last_run_rows"] = rows
    if duration_seconds is not None:
        system["last_run_duration_seconds"] = duration_seconds
    if error is not None:
        system["last_run_error"] = error
    elif "last_run_error" in system:
        system["last_run_error"] = None

    properties["system"] = system
    node.properties = properties


def _count_leading_failures(saved_query_id: UUID, engine: str, *, since: str | None = None) -> int:
    jobs = DataModelingJob.objects.filter(saved_query_id=saved_query_id, engine=str(engine))
    if since is not None:
        # Otherwise the failures that caused the suspension are still the most recent jobs, and one
        # new failure re-suspends the node we just resumed.
        jobs = jobs.filter(created_at__gt=dt.datetime.fromisoformat(since))
    statuses = jobs.order_by("-created_at").values_list("status", flat=True)[:CONSECUTIVE_FAILURES_TO_SUSPEND]
    count = 0
    for status in statuses:
        if status != DataModelingJobStatus.FAILED:
            break
        count += 1
    return count


@database_sync_to_async_pool
def maybe_suspend_node_for_engine(
    *,
    node_id: str,
    team_id: int,
    dag_id: str,
    saved_query_id: UUID,
    engine: str,
    reason: str,
    job_id: str,
) -> bool:
    """Suspend the node for an engine if its last N jobs for it all failed. True only on transition."""
    with transaction.atomic():
        node = Node.objects.select_for_update().get(id=node_id, team_id=team_id, dag_id=dag_id)
        if is_node_suspended(node, engine):
            return False
        since = suspension_reset_at(node, engine)
        if _count_leading_failures(saved_query_id, engine, since=since) < CONSECUTIVE_FAILURES_TO_SUSPEND:
            return False
        fingerprint = query_fingerprint(
            DataWarehouseSavedQuery.objects.filter(id=saved_query_id).values_list("query", flat=True).first()
        )
        mark_node_suspended(node, engine=engine, reason=reason, job_id=job_id, fingerprint=fingerprint)
        node.save()
    if str(engine) == DataModelingJobEngine.CLICKHOUSE.value:
        job = DataModelingJob.objects.get(id=job_id)
        job.error = (
            f"This model has been suspended after {CONSECUTIVE_FAILURES_TO_SUSPEND} consecutive failed "
            f"materializations. Error: {job.error}"
        )
        job.save(update_fields=["error"])
    return True


@database_sync_to_async_pool
def clear_node_suspension_for_engine(*, node_id: str, team_id: int, dag_id: str, engine: str) -> bool:
    with transaction.atomic():
        node = Node.objects.select_for_update().get(id=node_id, team_id=team_id, dag_id=dag_id)
        if not is_node_suspended(node, engine):
            return False
        clear_node_suspension(node, engine=engine)
        node.save()
    return True
