from posthog.warehouse.models import ExternalDataJob
from django.db.models import F
from posthog.warehouse.util import database_sync_to_async

CHUNK_SIZE = 10_000


def limit_paginated_generator(f):
    """
    Limits the number of items returned by a paginated generator.

    Must wrap a function with args:
    team_id: int,
    job_id (ExternalDataJob): str
    """

    def wrapped(**kwargs):
        job_id = kwargs.pop("job_id")
        team_id = kwargs.pop("team_id")

        model = ExternalDataJob.objects.get(id=job_id, team_id=team_id)
        gen = f(**kwargs)
        count = 0
        for item in gen:
            if count >= CHUNK_SIZE:
                ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(rows_synced=F("rows_synced") + count)
                count = 0

                model.refresh_from_db()

            if model.status == ExternalDataJob.Status.CANCELLED:
                break

            yield item
            count += len(item)

        ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(rows_synced=F("rows_synced") + count)

    return wrapped


async def check_limit(
    team_id: int,
    job_id: str,
    new_count: int,
):
    model = await aget_external_data_job(team_id, job_id)

    if new_count >= CHUNK_SIZE:
        await aupdate_job_count(job_id, team_id, new_count)
        new_count = 0

    status = model.status

    return new_count, status


@database_sync_to_async
def aget_external_data_job(team_id, job_id):
    return ExternalDataJob.objects.get(id=job_id, team_id=team_id)


@database_sync_to_async
def aupdate_job_count(job_id, team_id, new_count):
    ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(rows_synced=F("rows_synced") + new_count)
