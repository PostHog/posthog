from datetime import timedelta
from uuid import UUID

from celery import shared_task

from posthog.tasks.utils import CeleryQueue

REQUEST_TIME_LIMIT = timedelta(hours=1)


# acks_late, so a worker that stops before it claims the request leaves the message to another worker. The
# claim makes a second delivery a no-op. No retry, because the request records the failure, and staff
# retry with a new request. The time limit can kill an `enable` before its resave queues the flags cache
# rebuilds it coalesced. The team is below `serving` then, so flags read no realtime membership for it,
# and the stamps that later make its cohorts usable come with their own rebuild.
@shared_task(
    ignore_result=True,
    acks_late=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    time_limit=REQUEST_TIME_LIMIT.total_seconds(),
)
def process_realtime_cohort_request(team_id: int, request_id: str) -> None:
    from products.cohorts.backend.realtime_requests import (
        process_request,  # noqa: PLC0415 — realtime_requests imports this module to queue the task
    )

    process_request(team_id, UUID(request_id))
