import datetime as dt
from functools import partial

from django.db import transaction

from prometheus_client import Counter
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.data_warehouse.backend.tasks.tasks import schedule_external_data_failure_digest
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

FINALIZE_QUEUE_BATCHES_SWEPT = Counter(
    "dwh_finalize_queue_batches_swept",
    "Queue batches failed because their v3 job reached a terminal state before the queue drained",
)

FINALIZE_QUEUE_SWEEP_ERRORS = Counter(
    "dwh_finalize_queue_sweep_errors",
    "Errors swallowed while sweeping queue batches at job finalize",
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

        # The CDC halted states are absorbing: a loader finishing an in-flight batch after the
        # source broke (or a non-retryable error paused extraction) must not repaint the schema
        # healthy while syncing is stopped. Which markers halt a schema is the model's business
        # (cdc_halted) — this generic layer only honors the state.
        if schema.cdc_halted:
            logger.info(
                "dwh_schema_status_update_skipped_cdc_halted",
                job_id=job_id,
                schema_id=str(schema.id),
                requested_status=schema_status,
            )
        else:
            schema.status = schema_status
            schema.latest_error = latest_error
            schema.save(update_fields=["status", "latest_error", "updated_at"])

        # Every risky terminal write (any non-Completed terminal, plus the takeover-recovery
        # Completed flip) can leave still-claimable batches in the v3 queue; a straggler loaded
        # later can stale-overwrite newer data or flip this job's status. A normal v3 completion
        # has drained the queue by construction, so the common completion path stays queue-free.
        # on_commit: the queue is a separate Postgres; never call it holding these row locks.
        should_sweep_queue = (
            model.pipeline_version == ExternalDataJob.PipelineVersion.V3
            and status in TERMINAL_JOB_STATUSES
            and (status != ExternalDataJob.Status.COMPLETED or is_takeover_recovery)
        )
        if should_sweep_queue:
            transaction.on_commit(
                partial(_sweep_v3_queue_batches_swallowing_errors, job_id=job_id, status=status, logger=logger)
            )

    model.refresh_from_db()

    if is_first_terminal_transition:
        logger.debug("Emitting app metrics")
        emit_data_import_app_metrics(model)

        if status == ExternalDataJob.Status.FAILED:
            try:
                schedule_external_data_failure_digest(team_id)
            except Exception:
                logger.exception("Failed to schedule external data failure digest")

    return model


def _sweep_v3_queue_batches_swallowing_errors(
    *, job_id: str, status: ExternalDataJob.Status, logger: FilteringBoundLogger
) -> None:
    # A queue-DB error must never surface into the caller that just committed the status write.
    # The stale-stranded reconcile sweep on the loader retries what this misses.
    try:
        _sweep_v3_queue_batches(job_id=job_id, status=status, logger=logger)
    except Exception as e:
        FINALIZE_QUEUE_SWEEP_ERRORS.inc()
        logger.exception("dwh_finalize_queue_sweep_failed", job_id=job_id)
        capture_exception(e)


def _sweep_v3_queue_batches(*, job_id: str, status: ExternalDataJob.Status, logger: FilteringBoundLogger) -> None:
    """Fail any still-non-terminal queue batches of a v3 job that just went terminal."""
    # Deferred: the queue package imports back through this module (see postgres_queue.consumer),
    # so a top-level import would cycle.
    import psycopg

    from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

    from products.warehouse_sources.backend.facade.pipelines import BatchQueue

    conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
    try:
        swept = BatchQueue.fail_batches_for_job_sync(
            conn,
            job_id=job_id,
            reason=f"job finalized as {status} before its queue drained",
        )
    finally:
        conn.close()

    if swept:
        FINALIZE_QUEUE_BATCHES_SWEPT.inc(swept)
        logger.warning(
            "dwh_finalize_swept_queue_batches",
            job_id=job_id,
            status=status,
            batch_count=swept,
        )
