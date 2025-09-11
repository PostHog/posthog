from posthog.sync import database_sync_to_async
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource


def get_external_data_source(team_id: str, external_data_source_id: str) -> ExternalDataSource:
    return ExternalDataSource.objects.get(team_id=team_id, id=external_data_source_id)


@database_sync_to_async
def aget_running_job_for_schema(schema_id: str) -> ExternalDataJob | None:
    return (
        ExternalDataJob.objects.filter(schema_id=schema_id, status=ExternalDataJob.Status.RUNNING)
        .order_by("-created_at")
        .first()
    )


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
