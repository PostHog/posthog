"""Tell the Workflows product that a materialization job reached a terminal state.

The counterpart to ``products.workflows.backend.github_workflow_events``: write one internal
event per finished job, and let a workflow's trigger filters decide which views and outcomes
it cares about.
"""

import uuid

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event

from products.data_modeling.backend.models import DataModelingJob, DataModelingJobEngine, DataModelingJobStatus

logger = structlog.get_logger(__name__)

MATERIALIZATION_JOB_FINISHED_EVENT = "$materialization_job_finished"

_MATERIALIZATION_EVENT_NAMESPACE = uuid.UUID("7b1c6d2e-4f8a-4c3b-9e5d-2a6f8b0c1d3e")

# Status values a trigger filter compares against. Lowercase, unlike the job's stored status, so
# a filter reads like the rest of the event's properties.
_STATUS_PROPERTY = {
    DataModelingJobStatus.COMPLETED: "completed",
    DataModelingJobStatus.FAILED: "failed",
    DataModelingJobStatus.CANCELLED: "cancelled",
}


def emit_materialization_job_finished(job: DataModelingJob, *, duration_seconds: float | None = None) -> None:
    """Write one internal event for a job that just became Completed, Failed or Cancelled.

    Never raises: a trigger that misses a run must not fail the materialization behind it.
    Only the ClickHouse job is reported, because the DuckDB shadow writes its own job row for
    the same run and a workflow would otherwise fire twice.
    """
    status = _STATUS_PROPERTY.get(DataModelingJobStatus(job.status))
    if status is None or job.engine != DataModelingJobEngine.CLICKHOUSE or job.team_id is None:
        return

    saved_query = job.saved_query
    if saved_query is None or saved_query.deleted:
        return

    try:
        produce_internal_event(
            job.team_id,
            InternalEventEvent(
                event=MATERIALIZATION_JOB_FINISHED_EVENT,
                distinct_id=f"saved_query:{saved_query.id}",
                properties={
                    "job_id": str(job.id),
                    "view_id": str(saved_query.id),
                    "view_name": saved_query.name,
                    "status": status,
                    "rows_materialized": job.rows_materialized,
                    "duration_seconds": duration_seconds,
                    "error": job.error,
                    "workflow_id": job.workflow_id,
                    "parent_workflow_id": job.parent_workflow_id,
                },
                # Keyed on the job and outcome, so an activity retry that re-runs this emit
                # produces the same event id instead of a second run of the workflow.
                uuid=str(uuid.uuid5(_MATERIALIZATION_EVENT_NAMESPACE, f"{job.team_id}:{job.id}:{status}")),
            ),
        )
    except Exception:
        logger.exception(
            "materialization_workflow_event_produce_failed",
            team_id=job.team_id,
            job_id=str(job.id),
            saved_query_id=str(saved_query.id),
        )
