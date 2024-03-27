from posthog.warehouse.models import ExternalDataJob
from django.db.models import F
from posthog.warehouse.util import database_sync_to_async

CHUNK_SIZE = 10_000


async def check_limit(
    team_id: int,
    job_id: str,
    new_count: int,
):
    model = await aget_external_data_job(team_id, job_id)

    if new_count >= CHUNK_SIZE:
        new_count = 0

    status = model.status

    return new_count, status


@database_sync_to_async
def aget_external_data_job(team_id, job_id):
    return ExternalDataJob.objects.get(id=job_id, team_id=team_id)


@database_sync_to_async
def aupdate_job_count(job_id: str, team_id: int, count: int):
    ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(rows_synced=F("rows_synced") + count)
