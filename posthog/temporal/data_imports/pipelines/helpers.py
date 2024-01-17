from posthog.warehouse.models import ExternalDataJob
from django.db.models import F

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
