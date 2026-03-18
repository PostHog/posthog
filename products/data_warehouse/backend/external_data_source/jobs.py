from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


def update_external_job_status(
    job_id: str, team_id: int, status: ExternalDataJob.Status, latest_error: str | None
) -> ExternalDataJob:
    model = ExternalDataJob.objects.get(id=job_id, team_id=team_id)
    model.status = status
    model.latest_error = latest_error
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

    return model
