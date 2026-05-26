import uuid as uuid_lib
import asyncio
import builtins
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast

from django.conf import settings
from django.db.models import Prefetch

import structlog
from loginas.utils import is_impersonated_session
from temporalio import common

from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.util import (
    _fetch_persons_by_distinct_ids_via_personhog,
    _fetch_persons_by_uuids_via_personhog,
    delete_person,
    delete_persons_from_postgres,
)
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect
from posthog.temporal.session_replay.delete_recordings.types import DeletionConfig, RecordingsWithPersonInput

logger = structlog.get_logger(__name__)


@dataclass
class PersonProfileDeletionResult:
    deleted_count: int
    errors: list[uuid_lib.UUID] = field(default_factory=list)


# Columns required by the deletion path:
# - id, team_id: Person.delete() WHERE clause (single-partition delete on posthog_person_new)
# - uuid: ClickHouse tombstone, AsyncDeletion key, recording workflow id, activity log
# - version, created_at: delete_person() -> _delete_person() (Kafka tombstone payload)
# Everything else (notably ``properties``, a large JSONB) is excluded to keep row size small.
_PERSON_DELETION_COLUMNS = ("id", "team_id", "uuid", "version", "created_at")


def resolve_persons_for_deletion(
    team_id: int,
    uuids: builtins.list[str] | None,
    distinct_ids: builtins.list[str] | None,
) -> builtins.list[Person]:
    """Materialize Persons matching either uuids or distinct_ids.

    Goes straight to personhog, falling back to ORM only on error or if
    the client is not configured.
    """
    from posthog.personhog_client.client import get_personhog_client

    if not uuids and not distinct_ids:
        return []

    client = get_personhog_client()
    if client is not None:
        try:
            if uuids:
                return _fetch_persons_by_uuids_via_personhog(team_id, uuids)
            else:
                return _fetch_persons_by_distinct_ids_via_personhog(team_id, cast(builtins.list[str], distinct_ids))
        except Exception:
            logger.warning("resolve_persons_for_deletion_personhog_failure", team_id=team_id, exc_info=True)

    # ORM fallback
    persons_queryset = (
        Person.objects.filter(team_id=team_id)  # nosemgrep: no-direct-persons-db-orm
        .only(*_PERSON_DELETION_COLUMNS)
        .prefetch_related(
            Prefetch(
                "persondistinctid_set",
                # nosemgrep: no-direct-persons-db-orm
                queryset=PersonDistinctId.objects.filter(
                    team_id=team_id
                ).order_by(  # nosemgrep: no-direct-persons-db-orm
                    "id"
                ),  # nosemgrep: no-direct-persons-db-orm
                to_attr="distinct_ids_cache",
            )
        )
    )
    if uuids:
        persons_queryset = persons_queryset.filter(uuid__in=uuids)
    elif distinct_ids:
        person_ids = PersonDistinctId.objects.filter(  # nosemgrep: no-direct-persons-db-orm
            team_id=team_id, distinct_id__in=distinct_ids
        ).values_list(  # nosemgrep: no-direct-persons-db-orm
            "person_id", flat=True
        )
        persons_queryset = persons_queryset.filter(id__in=person_ids)
    return list(persons_queryset)


def delete_persons_profile(
    team_id: int,
    persons: builtins.list[Person],
    *,
    actor: User | None,
    request=None,
    organization_id=None,
) -> PersonProfileDeletionResult:
    """Run ClickHouse Kafka tombstones, then a single Postgres batch delete.

    Activity logging is performed only when both ``request`` and ``organization_id``
    are provided (i.e. from a DRF endpoint). Dagster ops should leave them as None.
    """
    deleted: builtins.list[Person] = []
    errors: builtins.list[uuid_lib.UUID] = []
    for person in persons:
        try:
            delete_person(person=person)
            deleted.append(person)
        except Exception:
            logger.exception("Failed to delete person", person_uuid=str(person.uuid))
            errors.append(person.uuid)
            continue
        if request is not None and organization_id is not None and actor is not None:
            log_activity(
                organization_id=organization_id,
                team_id=team_id,
                user=cast(User, actor),
                was_impersonated=is_impersonated_session(request),
                item_id=person.pk,
                scope="Person",
                activity="deleted",
                detail=Detail(name=str(person.uuid)),
            )

    if deleted:
        delete_persons_from_postgres(team_id, deleted)
    return PersonProfileDeletionResult(deleted_count=len(deleted), errors=errors)


def queue_person_event_deletion(
    team_id: int,
    persons: builtins.list[Person],
    *,
    actor: User | None,
) -> None:
    if not persons:
        return
    AsyncDeletion.objects.bulk_create(
        [
            AsyncDeletion(
                deletion_type=DeletionType.Person,
                team_id=team_id,
                key=str(person.uuid),
                created_by=actor,
            )
            for person in persons
        ],
        ignore_conflicts=True,
    )


def queue_person_recording_deletion(
    team_id: int,
    persons: builtins.list[Person],
    *,
    actor: User | None,
    reason: str = "person deletion",
) -> None:
    if not persons:
        return
    _start_recording_workflows(team_id, persons, actor, reason)


def _start_recording_workflows(
    team_id: int,
    persons: builtins.list[Person],
    actor: User | None,
    reason: str,
) -> None:
    """Kick off one ``delete-recordings-with-person`` workflow per person.

    The Temporal connection is established here (rather than in the caller) so
    that tests patching this seam don't need to mock ``sync_connect`` separately.
    """
    temporal = sync_connect()

    async def start_all_workflows():
        tasks = []
        for person in persons:
            workflow_input = RecordingsWithPersonInput(
                distinct_ids=person.distinct_ids,
                team_id=team_id,
                config=DeletionConfig(deleted_by=getattr(actor, "email", None), reason=reason),
            )
            workflow_id = f"delete-recordings-{team_id}-person-{person.uuid}-{uuid_lib.uuid4()}"
            tasks.append(
                temporal.start_workflow(
                    "delete-recordings-with-person",
                    workflow_input,
                    id=workflow_id,
                    task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )
        await asyncio.gather(*tasks)

    asyncio.run(start_all_workflows())
