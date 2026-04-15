import datetime as dt

from posthog.temporal.data_imports.metrics import emit_data_import_app_metrics

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

_TERMINAL_JOB_STATUSES = {
    ExternalDataJob.Status.COMPLETED,
    ExternalDataJob.Status.FAILED,
    ExternalDataJob.Status.BILLING_LIMIT_REACHED,
    ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW,
}


def update_external_job_status(
    job_id: str, team_id: int, status: ExternalDataJob.Status, latest_error: str | None
) -> ExternalDataJob:
    model = ExternalDataJob.objects.get(id=job_id, team_id=team_id)
    model.status = status
    model.latest_error = latest_error

    # Stamp finished_at once, here, when the job reaches a terminal state. This
    # used to happen at three different call sites with a follow-up save() —
    # consolidating lets the metric emitter below read a consistent value and
    # avoids bumping the timestamp forward if a redelivered message transitions
    # an already-terminal job.
    if status in _TERMINAL_JOB_STATUSES and model.finished_at is None:
        model.finished_at = dt.datetime.now(dt.UTC)

    model.save()

    if status == ExternalDataJob.Status.FAILED:
        schema_status: ExternalDataSchema.Status = ExternalDataSchema.Status.FAILED
    else:
        schema_status = status  # type: ignore

    schema = ExternalDataSchema.objects.get(id=model.schema_id, team_id=team_id)
    schema.status = schema_status
    schema.latest_error = latest_error
    schema.save()

    model.refresh_from_db()

    emit_data_import_app_metrics(model)

    return model
