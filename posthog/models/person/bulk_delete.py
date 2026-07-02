import uuid as uuid_lib
import asyncio
import builtins
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast

from django.conf import settings

import structlog
from temporalio import common

from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import Person
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


def resolve_persons_for_deletion(
    team_id: int,
    uuids: builtins.list[str] | None,
    distinct_ids: builtins.list[str] | None,
) -> builtins.list[Person]:
    """Materialize Persons matching either uuids or distinct_ids, via personhog."""
    from posthog.personhog_client.client import personhog_call

    if not uuids and not distinct_ids:
        return []

    # Unbounded distinct_ids: downstream recording deletion needs the full set per person.
    def _fetch() -> builtins.list[Person]:
        if uuids:
            return _fetch_persons_by_uuids_via_personhog(team_id, uuids)
        return _fetch_persons_by_distinct_ids_via_personhog(team_id, cast(builtins.list[str], distinct_ids))

    return personhog_call("resolve_persons_for_deletion", _fetch, caller_tag="persons/deletion-resolve")


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
                was_impersonated=is_impersonated(request),
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

        async def start_batch(batch: builtins.list[Person]) -> None:
            distinct_ids = sorted({distinct_id for person in batch for distinct_id in person.distinct_ids})
            if not distinct_ids:
                return
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

        await asyncio.gather(*(start_batch(batch) for batch in _chunk_persons(persons)))

    asyncio.run(start_all_workflows())
