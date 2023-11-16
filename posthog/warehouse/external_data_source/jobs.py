from posthog.warehouse.models.external_data_job import ExternalDataJob

def create_external_data_job(
    external_data_source_id: str,
    team_id: str
) -> ExternalDataJob:
    job = ExternalDataJob.objects.create(
        team_id=team_id,
        pipeline_id=external_data_source_id,
        status=ExternalDataJob.Type.RUNNING,
        rows_synced=0
    )

    return job
    