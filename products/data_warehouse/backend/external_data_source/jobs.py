import datetime as dt

from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.metrics import TERMINAL_JOB_STATUSES, emit_data_import_app_metrics

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


def update_external_job_status(
    job_id: str, team_id: int, status: ExternalDataJob.Status, logger: FilteringBoundLogger, latest_error: str | None
) -> ExternalDataJob:
    model = ExternalDataJob.objects.get(id=job_id, team_id=team_id)
    model.status = status
    model.latest_error = latest_error

    # Both the finished_at stamp and the metric emission must only fire on the
    # first terminal transition — a retried Temporal activity or redelivered
    # Kafka message can land here with the job already in a terminal state, and
    # re-emitting would inflate the counters.
    is_first_terminal_transition = status in TERMINAL_JOB_STATUSES and model.finished_at is None
    if is_first_terminal_transition:
        model.finished_at = dt.datetime.now(dt.UTC)

    model.save()

    if status == ExternalDataJob.Status.FAILED:
        schema_status: ExternalDataSchema.Status = ExternalDataSchema.Status.FAILED
    else:
        schema_status = status  # type: ignore

    if model.schema_id is None:
        raise ValueError(f"External data job {job_id} is not attached to a schema")

    schema = ExternalDataSchema.objects.get(id=model.schema_id, team_id=team_id)
    schema.status = schema_status
    schema.latest_error = latest_error
    schema.save()

    model.refresh_from_db()

    if is_first_terminal_transition:
        logger.debug("Emitting app metrics")
        emit_data_import_app_metrics(model)

    return model
