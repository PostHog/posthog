import uuid as uuid_lib
from collections import Counter
from collections.abc import Iterator

from django.http import HttpRequest

import structlog
from celery import shared_task

from posthog.helpers.impersonation import is_impersonated
from posthog.models.person import Person
from posthog.models.person.bulk_delete import process_queued_person_deletion
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# Small chunks keep a retry cheap: only the chunk holding a failing person is re-run.
PERSONS_PER_DELETION_TASK = 100


class PersonDeletionIncomplete(Exception):
    """Raised once the failed persons of a chunk have used up their attempts."""


# Attempts per person, including the first. Failed persons are requeued on their own rather than
# through Celery's retry, which would re-run the whole chunk: with the person kept, every person
# still resolves on a retry, so a chunk-wide re-run would start new recording workflows and
# training deletion for persons that already succeeded.
MAX_DELETION_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 60
RETRY_BACKOFF_MAX_SECONDS = 600


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def queue_person_deletion(
    team_id: int,
    persons: list[Person],
    *,
    delete_profile: bool,
    delete_recordings: bool,
    actor: User | None,
    request: HttpRequest | None,
    organization_id: uuid_lib.UUID | None,
) -> int:
    """Enqueue the distinct-ID-dependent deletion steps for ``persons``; returns how many were queued."""
    if not persons or not (delete_profile or delete_recordings):
        return 0
    was_impersonated = is_impersonated(request)
    uuids = [str(person.uuid) for person in persons]
    for chunk in _chunks(uuids, PERSONS_PER_DELETION_TASK):
        delete_persons_async.delay(
            team_id=team_id,
            person_uuids=chunk,
            delete_profile=delete_profile,
            delete_recordings=delete_recordings,
            actor_id=actor.pk if actor is not None else None,
            organization_id=str(organization_id) if organization_id is not None else None,
            was_impersonated=was_impersonated,
        )
    return len(uuids)


# Late ack plus reject-on-worker-lost redeliver the chunk when a worker restarts or is killed
# mid-run, instead of dropping a deletion the API already reported as queued. Redelivery is safe
# because every step is idempotent and deleted persons no longer resolve. Celery's own retry only
# covers exceptions escaping the task; recorded per-person failures requeue themselves below.
@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    dont_autoretry_for=(PersonDeletionIncomplete,),
    max_retries=3,
    retry_backoff=RETRY_BACKOFF_SECONDS,
    retry_backoff_max=RETRY_BACKOFF_MAX_SECONDS,
    retry_jitter=True,
)
@skip_team_scope_audit
def delete_persons_async(
    team_id: int,
    person_uuids: list[str],
    delete_profile: bool,
    delete_recordings: bool,
    actor_id: int | None,
    organization_id: str | None,
    was_impersonated: bool,
    attempt: int = 1,
) -> None:
    logger.info(
        "delete_persons_async started",
        team_id=team_id,
        person_count=len(person_uuids),
        delete_profile=delete_profile,
        delete_recordings=delete_recordings,
        attempt=attempt,
    )
    actor = User.objects.filter(pk=actor_id).first() if actor_id is not None else None
    result = process_queued_person_deletion(
        team_id,
        person_uuids,
        delete_profile=delete_profile,
        delete_recordings=delete_recordings,
        actor=actor,
        was_impersonated=was_impersonated,
        organization_id=uuid_lib.UUID(organization_id) if organization_id else None,
    )
    logger.info(
        "delete_persons_async finished",
        team_id=team_id,
        deleted_count=result.deleted_count,
        error_count=len(result.errors),
        attempt=attempt,
    )
    if not result.failures:
        return

    failures_by_step = Counter(failure.step.value for failure in result.failures)
    failed_uuids = [str(u) for u in result.errors]
    if attempt < MAX_DELETION_ATTEMPTS:
        countdown = min(RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1), RETRY_BACKOFF_MAX_SECONDS)
        logger.warning(
            "delete_persons_async requeueing failed persons",
            team_id=team_id,
            attempt=attempt,
            countdown_seconds=countdown,
            failures_by_step=dict(failures_by_step),
            failed_person_uuids=failed_uuids[:20],
        )
        delete_persons_async.apply_async(
            kwargs={
                "team_id": team_id,
                "person_uuids": failed_uuids,
                "delete_profile": delete_profile,
                "delete_recordings": delete_recordings,
                "actor_id": actor_id,
                "organization_id": organization_id,
                "was_impersonated": was_impersonated,
                "attempt": attempt + 1,
            },
            countdown=countdown,
        )
        return

    logger.error(
        "delete_persons_async gave up",
        team_id=team_id,
        attempt=attempt,
        failures_by_step=dict(failures_by_step),
        failed_person_uuids=failed_uuids[:20],
    )
    summary = ", ".join(f"{step}={count}" for step, count in failures_by_step.items())
    raise PersonDeletionIncomplete(
        f"team {team_id}: {len(failed_uuids)} persons failed after {attempt} attempts ({summary})"
    )
