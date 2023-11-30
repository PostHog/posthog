from uuid import UUID

from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_source import ExternalDataSource


def get_external_data_source(team_id: str, external_data_source_id: str) -> ExternalDataSource:
    return ExternalDataSource.objects.get(team_id=team_id, id=external_data_source_id)


def create_external_data_job(external_data_source_id: str, team_id: str) -> ExternalDataJob:
    job = ExternalDataJob.objects.create(
        team_id=team_id, pipeline_id=external_data_source_id, status=ExternalDataJob.Status.RUNNING, rows_synced=0
    )

    return job


def update_external_job_status(run_id: UUID, status: str, latest_error: str | None) -> ExternalDataJob:
    model = ExternalDataJob.objects.filter(id=run_id)
    updated = model.update(status=status, latest_error=latest_error)

    if not updated:
        raise ValueError(f"ExternalDataJob with id {run_id} not found.")

    return model.get()
