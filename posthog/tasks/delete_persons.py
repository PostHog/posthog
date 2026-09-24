import uuid as uuid_lib
from collections import Counter
from collections.abc import Iterator

from django.http import HttpRequest

import structlog
from celery import Task, shared_task

from posthog.helpers.impersonation import is_impersonated
from posthog.models.person import Person
from posthog.models.person.bulk_delete import (
    PERSON_DELETION_PERSONS_COUNTER,
    PersonDeletionStep,
    process_queued_person_deletion,
)
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

# Small chunks keep a retry cheap: only the chunk holding a failing person is re-run.
PERSONS_PER_DELETION_TASK = 100


class PersonDeletionIncomplete(Exception):
    """Raised once the failed persons of a chunk have used up their retries."""


# Retries per chunk. Failed persons are retried through Celery's retry with the person list
# narrowed to them, never by re-running the original chunk: with the person kept, every person
# still resolves on a retry, so a chunk-wide re-run would start new recording workflows and
# training deletion for persons that already succeeded.
MAX_DELETION_RETRIES = 3
RETRY_BACKOFF_SECONDS = 60
RETRY_BACKOFF_MAX_SECONDS = 600


def _retry_countdown(retries: int) -> int:
    return min(RETRY_BACKOFF_SECONDS * 2**retries, RETRY_BACKOFF_MAX_SECONDS)


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
    unmatched_distinct_ids: list[str] | None = None,
) -> int:
    """Enqueue the distinct-ID-dependent deletion steps for ``persons``; returns how many were queued.

    ``unmatched_distinct_ids`` ride on the first chunk so their replay session lookup runs in the
    task rather than in the request. They are sent even when no person resolved.
    """
    if not (delete_profile or delete_recordings):
        return 0
    uuids = [str(person.uuid) for person in persons]
    PERSON_DELETION_PERSONS_COUNTER.labels(path="queued", outcome="queued").inc(len(uuids))
    chunks = list(_chunks(uuids, PERSONS_PER_DELETION_TASK)) or ([[]] if unmatched_distinct_ids else [])
    was_impersonated = is_impersonated(request)
    for index, chunk in enumerate(chunks):
        delete_persons_async.delay(
            team_id=team_id,
            person_uuids=chunk,
            delete_profile=delete_profile,
            delete_recordings=delete_recordings,
            actor_id=actor.pk if actor is not None else None,
            organization_id=str(organization_id) if organization_id is not None else None,
            was_impersonated=was_impersonated,
            unmatched_distinct_ids=list(unmatched_distinct_ids or []) if index == 0 else [],
        )
    return len(uuids)


# Late ack plus reject-on-worker-lost redeliver the chunk when a worker restarts or is killed
# mid-run, instead of dropping a deletion the API already reported as queued. Redelivery is safe
# because every step is idempotent and deleted persons no longer resolve. There is deliberately no
# autoretry: a retry always goes through self.retry below, so a failed retry publish is rejected
# rather than re-running the original chunk.
@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=MAX_DELETION_RETRIES,
)
@skip_team_scope_audit
def delete_persons_async(
    self: Task,
    team_id: int,
    person_uuids: list[str],
    delete_profile: bool,
    delete_recordings: bool,
    actor_id: int | None,
    organization_id: str | None,
    was_impersonated: bool,
    unmatched_distinct_ids: list[str] | None = None,
) -> None:
    unmatched_distinct_ids = unmatched_distinct_ids or []
    retries = self.request.retries
    logger.info(
        "delete_persons_async started",
        team_id=team_id,
        person_count=len(person_uuids),
        unmatched_distinct_id_count=len(unmatched_distinct_ids),
        delete_profile=delete_profile,
        delete_recordings=delete_recordings,
        retries=retries,
    )
    try:
        actor = User.objects.filter(pk=actor_id).first() if actor_id is not None else None
        result = process_queued_person_deletion(
            team_id,
            person_uuids,
            delete_profile=delete_profile,
            delete_recordings=delete_recordings,
            actor=actor,
            was_impersonated=was_impersonated,
            organization_id=uuid_lib.UUID(organization_id) if organization_id else None,
            unmatched_distinct_ids=unmatched_distinct_ids,
        )
    except Exception as exc:
        # Nothing per person was recorded, so the same arguments go round again.
        logger.exception("delete_persons_async crashed", team_id=team_id, retries=retries)
        raise self.retry(exc=exc, countdown=_retry_countdown(retries))

    logger.info(
        "delete_persons_async finished",
        team_id=team_id,
        deleted_count=result.deleted_count,
        error_count=len(result.errors),
        retries=retries,
    )
    if not result.failures:
        return

    failures_by_step = Counter(failure.step.value for failure in result.failures)
    failed_uuids = [str(u) for u in result.errors]
    # A training failure with no person is the unmatched distinct IDs; they come back on the retry.
    unmatched_failed = any(
        f.step is PersonDeletionStep.QUEUE_TRAINING_DELETION and f.person_uuid is None for f in result.failures
    )
    summary = ", ".join(f"{step}={count}" for step, count in failures_by_step.items())
    logger.warning(
        "delete_persons_async retrying failed persons",
        team_id=team_id,
        retries=retries,
        failures_by_step=dict(failures_by_step),
        failed_person_uuids=failed_uuids[:20],
    )
    # Past max_retries this raises the exception given here instead of scheduling another run.
    raise self.retry(
        kwargs={
            "team_id": team_id,
            "person_uuids": failed_uuids,
            "delete_profile": delete_profile,
            "delete_recordings": delete_recordings,
            "actor_id": actor_id,
            "organization_id": organization_id,
            "was_impersonated": was_impersonated,
            "unmatched_distinct_ids": unmatched_distinct_ids if unmatched_failed else [],
        },
        countdown=_retry_countdown(retries),
        exc=PersonDeletionIncomplete(
            f"team {team_id}: {len(failed_uuids)} persons failed after {retries + 1} attempts ({summary})"
        ),
    )
