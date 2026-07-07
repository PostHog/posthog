import datetime as dt

from django.db import transaction

from prometheus_client import Counter
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.tasks import (
    EXTERNAL_DATA_FAILURE_DIGEST_DELAY_SECONDS,
    EXTERNAL_DATA_FAILURE_DIGEST_SCHEDULED_COUNTER,
    send_external_data_failure_digest_task,
)
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema
from products.warehouse_sources.backend.facade.pipelines import (
    LOCK_TAKEOVER_LATEST_ERROR,
    TERMINAL_JOB_STATUSES,
    emit_data_import_app_metrics,
)

JOB_STATUS_TRANSITION_REJECTED = Counter(
    "dwh_job_status_transition_rejected",
    "Job status transition rejected because the job was already in a different terminal state",
)


def update_external_job_status(
    job_id: str, team_id: int, status: ExternalDataJob.Status, logger: FilteringBoundLogger, latest_error: str | None
) -> ExternalDataJob:
    is_first_terminal_transition = False
    with transaction.atomic():
        model = ExternalDataJob.objects.select_for_update().get(id=job_id, team_id=team_id)

        # The loader may finish a run after lock takeover force-failed its job; only the
        # exact takeover sentinel unseals Failed -> Completed — genuine failures stay absorbing.
        is_takeover_recovery = (
            model.status == ExternalDataJob.Status.FAILED
            and status == ExternalDataJob.Status.COMPLETED
            and model.latest_error == LOCK_TAKEOVER_LATEST_ERROR
        )

        # Terminal states are absorbing: same-status retries pass, different statuses are rejected.
        if model.status in TERMINAL_JOB_STATUSES and model.status != status and not is_takeover_recovery:
            logger.warning(
                "dwh_job_status_transition_rejected",
                job_id=job_id,
                current_status=model.status,
                requested_status=status,
            )
            JOB_STATUS_TRANSITION_REJECTED.inc()
            return model

        if is_takeover_recovery:
            logger.info(
                "dwh_job_completed_after_lock_takeover",
                job_id=job_id,
            )

        model.status = status
        model.latest_error = latest_error

        # Only stamp finished_at and emit metrics on the first terminal transition. Takeover
        # recovery re-stamps: the Failed stamp predates the load and never emitted success metrics.
        is_first_terminal_transition = status in TERMINAL_JOB_STATUSES and (
            model.finished_at is None or is_takeover_recovery
        )
        update_fields = ["status", "latest_error", "updated_at"]
        if is_first_terminal_transition:
            model.finished_at = dt.datetime.now(dt.UTC)
            update_fields.append("finished_at")

        # Scoped save so concurrent F-updates to rows_synced aren't clobbered.
        model.save(update_fields=update_fields)

        if status == ExternalDataJob.Status.FAILED:
            schema_status: ExternalDataSchema.Status = ExternalDataSchema.Status.FAILED
        else:
            schema_status = status  # type: ignore

        if model.schema_id is None:
            raise ValueError(f"External data job {job_id} is not attached to a schema")

        schema = ExternalDataSchema.objects.select_for_update().get(id=model.schema_id, team_id=team_id)
        schema.status = schema_status
        schema.latest_error = latest_error
        schema.save(update_fields=["status", "latest_error", "updated_at"])

    model.refresh_from_db()

    if is_first_terminal_transition:
        logger.debug("Emitting app metrics")
        emit_data_import_app_metrics(model)

        if status == ExternalDataJob.Status.FAILED:
            try:
                send_external_data_failure_digest_task.apply_async(
                    args=[team_id], countdown=EXTERNAL_DATA_FAILURE_DIGEST_DELAY_SECONDS
                )
                EXTERNAL_DATA_FAILURE_DIGEST_SCHEDULED_COUNTER.labels(trigger="inline").inc()
            except Exception:
                logger.exception("Failed to schedule external data failure digest")

    return model
