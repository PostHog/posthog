from uuid import UUID

from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_source import ExternalDataSource
from django.db import close_old_connections


def get_external_data_source(team_id: str, external_data_source_id: str) -> ExternalDataSource:
    return ExternalDataSource.objects.get(team_id=team_id, id=external_data_source_id)


def get_external_data_job(team_id: str, run_id: str) -> ExternalDataJob:
    close_old_connections()
    return ExternalDataJob.objects.select_related("pipeline").get(id=run_id, team_id=team_id)


def create_external_data_job(
    external_data_source_id: UUID,
    workflow_id: str,
    team_id: str,
) -> ExternalDataJob:
    job = ExternalDataJob.objects.create(
        team_id=team_id,
        pipeline_id=external_data_source_id,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id=workflow_id,
    )

    return job


def update_external_job_status(run_id: UUID, team_id: str, status: str, latest_error: str | None) -> ExternalDataJob:
    model = ExternalDataJob.objects.get(id=run_id, team_id=team_id)
    model.status = status
    model.latest_error = latest_error
    model.save()

    pipeline = ExternalDataSource.objects.get(id=model.pipeline_id, team_id=team_id)
    pipeline.status = status
    pipeline.save()

    model.refresh_from_db()

    return model
