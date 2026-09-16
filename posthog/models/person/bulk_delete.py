import uuid as uuid_lib
import asyncio
import builtins
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast

from django.conf import settings

import structlog
from temporalio import common

from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Detail, LogActivityEntry, bulk_log_activity
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import Person
from posthog.models.person.util import (
    DistinctIdForPerson,
    _batched_get_distinct_ids_for_persons,
    _fetch_persons_by_distinct_ids_via_personhog,
    _fetch_persons_by_uuids_via_personhog,
    _paginated_get_distinct_ids_for_person,
    delete_person,
    delete_persons_from_postgres,
)
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect
from posthog.temporal.session_replay.delete_recordings.types import DeletionConfig, RecordingsWithPersonInput

from products.ai_training.backend.facade.api import queue_person_training_deletion

logger = structlog.get_logger(__name__)


@dataclass
class PersonProfileDeletionResult:
    deleted_count: int
    errors: list[uuid_lib.UUID] = field(default_factory=list)


def resolve_persons_for_deletion(
    team_id: int,
    uuids: builtins.list[str] | None,
    distinct_ids: builtins.list[str] | None,
    *,
    with_distinct_ids: bool = True,
) -> builtins.list[Person]:
    """Materialize Persons matching either uuids or distinct_ids, via personhog.

    With ``with_distinct_ids`` the fetch of each person's distinct IDs is unbounded, which the
    synchronous callers need because recording deletion wants the full set per person. The
    queued path passes False and pages through them later, inside the task.
    """
    from posthog.personhog_client.client import personhog_call

    if not uuids and not distinct_ids:
        return []

    limit = None if with_distinct_ids else 0

    def _fetch() -> builtins.list[Person]:
        if uuids:
            return _fetch_persons_by_uuids_via_personhog(team_id, uuids, distinct_id_limit=limit)
        return _fetch_persons_by_distinct_ids_via_personhog(
            team_id, cast(builtins.list[str], distinct_ids), distinct_id_limit=limit
        )

    return personhog_call("resolve_persons_for_deletion", _fetch, caller_tag="persons/deletion-resolve")


def delete_persons_profile(
    team_id: int,
    persons: builtins.list[Person],
    *,
    actor: User | None,
    request=None,
    organization_id=None,
    queue_ai_training_deletion: bool = True,
) -> PersonProfileDeletionResult:
    """Run ClickHouse Kafka tombstones, then a single Postgres batch delete.

    Activity logging is performed only when both ``organization_id`` and ``actor``
    are provided (i.e. from a DRF endpoint). Dagster ops should leave them as None.
    """
    from posthog.personhog_client.client import personhog_call

    if queue_ai_training_deletion:
        queue_person_training_deletion(
            team_id, [distinct_id for person in persons for distinct_id in person.distinct_ids]
        )
    # A missing map entry (or a failed batch fetch) passes None below, making delete_person
    # fall back to its own per-person lookup so failure isolation is preserved.
    distinct_ids_by_person: dict[int, builtins.list[DistinctIdForPerson]] = {}
    try:
        distinct_ids_by_person = personhog_call(
            "get_distinct_ids_for_deletion",
            lambda: _batched_get_distinct_ids_for_persons(team_id, [person.pk for person in persons]),
            caller_tag="persons/deletion-distinct-ids",
        )
    except Exception:
        logger.exception("Batched distinct-id fetch failed, falling back to per-person lookups")

    return _tombstone_and_delete_persons(
        team_id,
        persons,
        lambda person: distinct_ids_by_person.get(person.pk),
        actor=actor,
        was_impersonated=is_impersonated(request),
        organization_id=organization_id,
    )


# Page size for the keyset walk over a person's distinct IDs. Each page is one bounded RPC, so a
# person with hundreds of thousands of distinct IDs no longer hits the personhog request timeout.
QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE = 5000


def process_queued_person_deletion(
    team_id: int,
    person_uuids: builtins.list[str],
    *,
    delete_profile: bool,
    delete_recordings: bool,
    actor: User | None,
    was_impersonated: bool,
    organization_id: uuid_lib.UUID | None,
) -> PersonProfileDeletionResult:
    """Run every distinct-ID-dependent deletion step for ``person_uuids`` from a background task.

    Persons are re-resolved without distinct IDs, then each person's distinct IDs are paged
    through with keyset pagination. There is no unbounded fallback: a failed page fetch marks
    that person as an error and skips it in every later step, so the caller can retry it.
    Persons that no longer exist (already deleted by an earlier attempt) resolve to nothing.
    """
    from posthog.personhog_client.client import personhog_call

    persons = personhog_call(
        "resolve_persons_for_queued_deletion",
        lambda: _fetch_persons_by_uuids_via_personhog(team_id, person_uuids, distinct_id_limit=0),
        caller_tag="persons/deletion-resolve",
    )

    def _fetch_distinct_ids(person_id: int) -> builtins.list[DistinctIdForPerson]:
        return personhog_call(
            "get_distinct_ids_for_queued_deletion",
            lambda: _paginated_get_distinct_ids_for_person(
                team_id, person_id, page_size=QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE
            ),
            caller_tag="persons/deletion-distinct-ids",
        )

    distinct_ids_by_person: dict[int, builtins.list[DistinctIdForPerson]] = {}
    fetched: builtins.list[Person] = []
    errors: builtins.list[uuid_lib.UUID] = []
    for person in persons:
        try:
            distinct_ids_by_person[person.pk] = _fetch_distinct_ids(person.pk)
        except Exception:
            logger.exception("Failed to fetch distinct IDs for person deletion", person_uuid=str(person.uuid))
            errors.append(person.uuid)
            continue
        person._distinct_ids = [d.id for d in distinct_ids_by_person[person.pk]]
        fetched.append(person)

    if delete_profile or delete_recordings:
        queue_person_training_deletion(
            team_id, [distinct_id for person in fetched for distinct_id in person.distinct_ids]
        )
    if delete_recordings:
        queue_person_recording_deletion(team_id, fetched, actor=actor, queue_ai_training_deletion=False)

    if not delete_profile:
        return PersonProfileDeletionResult(deleted_count=0, errors=errors)

    result = _tombstone_and_delete_persons(
        team_id,
        fetched,
        lambda person: distinct_ids_by_person[person.pk],
        actor=actor,
        was_impersonated=was_impersonated,
        organization_id=organization_id,
    )
    return PersonProfileDeletionResult(deleted_count=result.deleted_count, errors=[*errors, *result.errors])


def _tombstone_and_delete_persons(
    team_id: int,
    persons: builtins.list[Person],
    distinct_ids_for: Callable[[Person], builtins.list[DistinctIdForPerson] | None],
    *,
    actor: User | None,
    was_impersonated: bool,
    organization_id: uuid_lib.UUID | None,
) -> PersonProfileDeletionResult:
    """Tombstone each person in ClickHouse, log the deletions, then batch-delete the survivors from Postgres."""
    deleted: builtins.list[Person] = []
    errors: builtins.list[uuid_lib.UUID] = []
    for person in persons:
        try:
            delete_person(person=person, distinct_ids=distinct_ids_for(person))
            deleted.append(person)
        except Exception:
            logger.exception("Failed to delete person", person_uuid=str(person.uuid))
            errors.append(person.uuid)

    if organization_id is not None and actor is not None:
        bulk_log_activity(
            [
                LogActivityEntry(
                    organization_id=organization_id,
                    team_id=team_id,
                    user=cast(User, actor),
                    was_impersonated=was_impersonated,
                    item_id=person.pk,
                    scope="Person",
                    activity="deleted",
                    detail=Detail(name=str(person.uuid)),
                )
                for person in deleted
            ]
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
    queue_ai_training_deletion: bool = True,
) -> None:
    if not persons:
        return
    if queue_ai_training_deletion:
        queue_person_training_deletion(
            team_id, [distinct_id for person in persons for distinct_id in person.distinct_ids]
        )
    _start_recording_workflows(team_id, persons, actor, reason)


# Batch persons per workflow (not one each) to bound concurrent ClickHouse load queries; cap distinct IDs per chunk to stay under Temporal's payload limit.
_RECORDING_DELETION_PERSONS_PER_WORKFLOW = 100
_MAX_CONCURRENT_WORKFLOW_STARTS = 20
_MAX_DISTINCT_IDS_PER_WORKFLOW = 2000


def _chunk_persons(persons: builtins.list[Person]) -> Iterator[builtins.list[Person]]:
    """Group persons into workflow batches, bounded by both person and distinct-ID count."""
    batch: builtins.list[Person] = []
    batch_distinct_ids = 0
    for person in persons:
        person_distinct_ids = len(person.distinct_ids)
        over_caps = len(batch) >= _RECORDING_DELETION_PERSONS_PER_WORKFLOW or (
            batch_distinct_ids + person_distinct_ids > _MAX_DISTINCT_IDS_PER_WORKFLOW
        )
        if batch and over_caps:
            yield batch
            batch = []
            batch_distinct_ids = 0
        batch.append(person)
        batch_distinct_ids += person_distinct_ids
    if batch:
        yield batch


def _start_recording_workflows(
    team_id: int,
    persons: builtins.list[Person],
    actor: User | None,
    reason: str,
) -> None:
    """Kick off ``delete-recordings-with-person`` workflows, batching persons per run.

    The Temporal connection is established here (rather than in the caller) so
    that tests patching this seam don't need to mock ``sync_connect`` separately.
    """
    temporal = sync_connect()
    config = DeletionConfig(deleted_by=getattr(actor, "email", None) or "", reason=reason)

    async def start_all_workflows():
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_WORKFLOW_STARTS)

        async def start_workflow(distinct_ids: builtins.list[str]) -> None:
            workflow_input = RecordingsWithPersonInput(distinct_ids=distinct_ids, team_id=team_id, config=config)
            workflow_id = f"delete-recordings-{team_id}-persons-{uuid_lib.uuid4()}"
            async with semaphore:
                await temporal.start_workflow(
                    "delete-recordings-with-person",
                    workflow_input,
                    id=workflow_id,
                    task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )

        # A single person can carry more distinct IDs than the per-workflow cap, so the batch's
        # distinct IDs are split again here rather than trusting the person-level chunking alone.
        starts = [
            start_workflow(distinct_ids[i : i + _MAX_DISTINCT_IDS_PER_WORKFLOW])
            for batch in _chunk_persons(persons)
            for distinct_ids in [sorted({distinct_id for person in batch for distinct_id in person.distinct_ids})]
            for i in range(0, len(distinct_ids), _MAX_DISTINCT_IDS_PER_WORKFLOW)
        ]
        await asyncio.gather(*starts)

    asyncio.run(start_all_workflows())
