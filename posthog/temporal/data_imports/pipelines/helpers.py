from posthog.warehouse.models import ExternalDataJob

CHUNK_SIZE = 10000


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
                model.rows_synced += count
                model.save()
                count = 0

            yield item
            count += len(item)

        model.rows_synced += count
        model.save()

    return wrapped
