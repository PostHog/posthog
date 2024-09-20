from uuid import UUID
from posthog.warehouse.util import database_sync_to_async
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource


def get_external_data_source(team_id: str, external_data_source_id: str) -> ExternalDataSource:
    return ExternalDataSource.objects.get(team_id=team_id, id=external_data_source_id)


def create_external_data_job(
    external_data_source_id: UUID,
    external_data_schema_id: UUID,
    workflow_id: str,
    workflow_run_id: str,
    team_id: int,
) -> ExternalDataJob:
    job = ExternalDataJob.objects.create(
        team_id=team_id,
        pipeline_id=external_data_source_id,
        schema_id=external_data_schema_id,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
    )

    return job


@database_sync_to_async
def aupdate_external_job_status(
    job_id: str, team_id: int, status: ExternalDataJob.Status, latest_error: str | None
) -> ExternalDataJob:
    model = ExternalDataJob.objects.get(id=job_id, team_id=team_id)
    model.status = status
    model.latest_error = latest_error
    model.save()

    if status == ExternalDataJob.Status.FAILED:
        schema_status: ExternalDataSchema.Status = ExternalDataSchema.Status.ERROR
    else:
        schema_status = status  # type: ignore

    schema = ExternalDataSchema.objects.get(id=model.schema_id, team_id=team_id)
    schema.status = schema_status
    schema.save()

    model.refresh_from_db()

    return model
