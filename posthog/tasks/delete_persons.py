import uuid as uuid_lib
from collections.abc import Iterator

from django.http import HttpRequest

import structlog
from celery import shared_task

from posthog.helpers.impersonation import is_impersonated
from posthog.models.person import Person
from posthog.models.person.bulk_delete import delete_persons_profile_by_uuids
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)

# Small chunks keep a retry cheap: only the chunk holding a failing person is re-run.
PERSONS_PER_DELETION_TASK = 100


class PersonDeletionIncomplete(Exception):
    """Raised so Celery retries the chunk; persons already deleted are not re-resolved on retry."""


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def queue_person_profile_deletion(
    team_id: int,
    persons: list[Person],
    *,
    actor: User | None,
    request: HttpRequest | None,
    organization_id: uuid_lib.UUID | None,
) -> int:
    """Enqueue background profile deletion for ``persons`` and return how many were queued."""
    if not persons:
        return 0
    was_impersonated = is_impersonated(request)
    uuids = [str(person.uuid) for person in persons]
    for chunk in _chunks(uuids, PERSONS_PER_DELETION_TASK):
        delete_persons_profile_async.delay(
            team_id=team_id,
            person_uuids=chunk,
            actor_id=actor.pk if actor is not None else None,
            organization_id=str(organization_id) if organization_id is not None else None,
            was_impersonated=was_impersonated,
        )
    return len(uuids)


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=60,
    retry_backoff_max=600,
    retry_jitter=True,
)
@skip_team_scope_audit
def delete_persons_profile_async(
    team_id: int,
    person_uuids: list[str],
    actor_id: int | None,
    organization_id: str | None,
    was_impersonated: bool,
) -> None:
    logger.info("delete_persons_profile_async started", team_id=team_id, person_count=len(person_uuids))
    actor = User.objects.filter(pk=actor_id).first() if actor_id is not None else None
    result = delete_persons_profile_by_uuids(
        team_id,
        person_uuids,
        actor=actor,
        was_impersonated=was_impersonated,
        organization_id=uuid_lib.UUID(organization_id) if organization_id else None,
    )
    logger.info(
        "delete_persons_profile_async finished",
        team_id=team_id,
        deleted_count=result.deleted_count,
        error_count=len(result.errors),
    )
    if result.errors:
        raise PersonDeletionIncomplete(
            f"{len(result.errors)} of {len(person_uuids)} persons failed to delete for team {team_id}"
        )
