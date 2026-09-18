import uuid as uuid_lib
import asyncio
import builtins
from collections.abc import Callable, Iterable, Iterator
from dataclasses import field
from datetime import timedelta
from enum import StrEnum
from typing import cast

from django.conf import settings

import structlog
from prometheus_client import Counter, Histogram
from temporalio import common

from posthog.dataclasses import frozen
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import ActivityLog, Detail, LogActivityEntry, bulk_log_activity
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


class PersonDeletionStep(StrEnum):
    """The steps of a person deletion, in the order they run. Each failure names exactly one."""

    RESOLVE_PERSONS = "resolve_persons"
    FETCH_DISTINCT_IDS = "fetch_distinct_ids"
    QUEUE_TRAINING_DELETION = "queue_training_deletion"
    QUEUE_RECORDING_DELETION = "queue_recording_deletion"
    TOMBSTONE_CLICKHOUSE = "tombstone_clickhouse"
    DELETE_POSTGRES = "delete_postgres"
    LOG_ACTIVITY = "log_activity"


PERSON_DELETION_STEP_FAILURES_COUNTER = Counter(
    "posthog_person_deletion_step_failures_total",
    "Person deletion steps that raised, labelled by the step so a failing dependency is visible on its own.",
    labelnames=["step"],
)

# path: "sync" for the request-time delete, "queued" for the Celery task.
# outcome: "queued" when handed to the task, "deleted" once removed, "failed" per person per attempt.
PERSON_DELETION_PERSONS_COUNTER = Counter(
    "posthog_person_deletion_persons_total",
    "Persons handled by a deletion, by path and per-attempt outcome.",
    labelnames=["path", "outcome"],
)

PERSON_DELETION_DISTINCT_IDS_PER_PERSON = Histogram(
    "posthog_person_deletion_distinct_ids_per_person",
    "Distinct IDs fetched per person by the queued deletion, which shows how wide deleted persons are.",
    buckets=(1, 10, 100, 1_000, 10_000, 100_000, 1_000_000, float("inf")),
)


def _observe_person_outcomes(path: str, result: "PersonProfileDeletionResult") -> None:
    PERSON_DELETION_PERSONS_COUNTER.labels(path=path, outcome="deleted").inc(result.deleted_count)
    PERSON_DELETION_PERSONS_COUNTER.labels(path=path, outcome="failed").inc(len(result.errors))


@frozen
class PersonDeletionFailure:
    step: PersonDeletionStep
    # None when the step failed before any person was resolved.
    person_uuid: uuid_lib.UUID | None
    error: str


@frozen
class PersonProfileDeletionResult:
    deleted_count: int
    failures: list[PersonDeletionFailure] = field(default_factory=list)

    @property
    def errors(self) -> list[uuid_lib.UUID]:
        """Distinct UUIDs of persons that failed at any step, in first-failure order."""
        seen: dict[uuid_lib.UUID, None] = {}
        for failure in self.failures:
            if failure.person_uuid is not None:
                seen.setdefault(failure.person_uuid, None)
        return list(seen)


def _record_step_failure(
    failures: builtins.list[PersonDeletionFailure],
    *,
    step: PersonDeletionStep,
    team_id: int,
    exc: Exception,
    person_uuids: Iterable[uuid_lib.UUID | None],
) -> None:
    """Record one step failure. Call from inside the ``except`` block so the traceback is logged."""
    uuids = list(person_uuids) or [None]
    PERSON_DELETION_STEP_FAILURES_COUNTER.labels(step=step.value).inc()
    logger.exception(
        "person_deletion.step_failed",
        step=step.value,
        team_id=team_id,
        person_count=len([u for u in uuids if u is not None]),
        person_uuids=[str(u) for u in uuids[:20] if u is not None],
        error_type=type(exc).__name__,
    )
    error = f"{type(exc).__name__}: {exc}"
    failures.extend(PersonDeletionFailure(step=step, person_uuid=u, error=error) for u in uuids)


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
    queued path passes False and pages through them later, inside the task; a person resolved
    by distinct ID then carries only the requested distinct IDs that matched it.
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

    Activity logging is performed only when ``organization_id`` is provided (i.e. from a
    DRF endpoint). Dagster ops should leave it and ``actor`` as None.
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

    result = _tombstone_and_delete_persons(
        team_id,
        persons,
        lambda person: distinct_ids_by_person.get(person.pk),
        actor=actor,
        was_impersonated=is_impersonated(request),
        organization_id=organization_id,
    )
    _observe_person_outcomes("sync", result)
    return result


# Page size for the keyset walk over a person's distinct IDs. Each page is one bounded RPC, so a
# person with hundreds of thousands of distinct IDs no longer hits the personhog request timeout.
QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE = 5000

# A task chunk is sized by person count, which says nothing about how many distinct IDs it holds.
# The deletion steps run once this many distinct IDs are in memory, so several wide persons in one
# chunk cannot pile up on a worker; the bound is this cap plus one person's worth of IDs.
QUEUED_DELETION_DISTINCT_IDS_PER_BATCH = 20_000


@frozen
class _QueuedDeletionOptions:
    delete_profile: bool
    delete_recordings: bool
    actor: User | None
    was_impersonated: bool
    organization_id: uuid_lib.UUID | None


def process_queued_person_deletion(
    team_id: int,
    person_uuids: builtins.list[str],
    *,
    delete_profile: bool,
    delete_recordings: bool,
    actor: User | None,
    was_impersonated: bool,
    organization_id: uuid_lib.UUID | None,
    unmatched_distinct_ids: builtins.list[str] | None = None,
) -> PersonProfileDeletionResult:
    """Run every distinct-ID-dependent deletion step for ``person_uuids`` from a background task.

    ``unmatched_distinct_ids`` are requested distinct IDs that resolved to no person. They can
    still own replay sessions, so their training deletion is queued here too; a failure is
    recorded against the training step with no person.

    Persons are re-resolved without distinct IDs, then each person's distinct IDs are paged
    through with keyset pagination. There is no unbounded fallback: a failed page fetch marks
    that person as an error and skips it in every later step, so the caller can retry it.
    Persons that no longer exist (already deleted by an earlier attempt) resolve to nothing.

    Every failure is recorded against the step it happened in. The profile delete only runs
    when the steps before it succeeded, because it removes the distinct IDs a retry of those
    steps would need.
    """
    from posthog.personhog_client.client import personhog_call

    options = _QueuedDeletionOptions(
        delete_profile=delete_profile,
        delete_recordings=delete_recordings,
        actor=actor,
        was_impersonated=was_impersonated,
        organization_id=organization_id,
    )
    failures: builtins.list[PersonDeletionFailure] = []
    requested = [uuid_lib.UUID(u) for u in person_uuids]

    try:
        persons = personhog_call(
            "resolve_persons_for_queued_deletion",
            lambda: _fetch_persons_by_uuids_via_personhog(team_id, person_uuids, distinct_id_limit=0),
            caller_tag="persons/deletion-resolve",
        )
    except Exception as exc:
        _record_step_failure(
            failures, step=PersonDeletionStep.RESOLVE_PERSONS, team_id=team_id, exc=exc, person_uuids=requested
        )
        persons = []

    def _fetch_distinct_ids(person_id: int) -> builtins.list[DistinctIdForPerson]:
        return personhog_call(
            "get_distinct_ids_for_queued_deletion",
            lambda: _paginated_get_distinct_ids_for_person(
                team_id, person_id, page_size=QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE
            ),
            caller_tag="persons/deletion-distinct-ids",
        )

    deleted_count = 0
    batch: builtins.list[Person] = []
    batch_distinct_ids: dict[int, builtins.list[DistinctIdForPerson]] = {}
    batch_distinct_id_count = 0
    for person in persons:
        try:
            distinct_ids = _fetch_distinct_ids(person.pk)
        except Exception as exc:
            _record_step_failure(
                failures,
                step=PersonDeletionStep.FETCH_DISTINCT_IDS,
                team_id=team_id,
                exc=exc,
                person_uuids=[person.uuid],
            )
            continue
        PERSON_DELETION_DISTINCT_IDS_PER_PERSON.observe(len(distinct_ids))
        person._distinct_ids = [d.id for d in distinct_ids]
        batch.append(person)
        batch_distinct_ids[person.pk] = distinct_ids
        batch_distinct_id_count += len(distinct_ids)
        if batch_distinct_id_count >= QUEUED_DELETION_DISTINCT_IDS_PER_BATCH:
            deleted_count += _run_batch_and_release(team_id, batch, batch_distinct_ids, failures, options)
            batch, batch_distinct_ids, batch_distinct_id_count = [], {}, 0
    if batch:
        deleted_count += _run_batch_and_release(team_id, batch, batch_distinct_ids, failures, options)

    if unmatched_distinct_ids:
        try:
            queue_person_training_deletion(team_id, unmatched_distinct_ids)
        except Exception as exc:
            _record_step_failure(
                failures, step=PersonDeletionStep.QUEUE_TRAINING_DELETION, team_id=team_id, exc=exc, person_uuids=[]
            )

    result = PersonProfileDeletionResult(deleted_count=deleted_count, failures=failures)
    _observe_person_outcomes("queued", result)
    return result


def _run_batch_and_release(
    team_id: int,
    persons: builtins.list[Person],
    distinct_ids_by_person: dict[int, builtins.list[DistinctIdForPerson]],
    failures: builtins.list[PersonDeletionFailure],
    options: _QueuedDeletionOptions,
) -> int:
    deleted = _run_queued_deletion_steps(team_id, persons, distinct_ids_by_person, failures, options)
    # The resolved person objects outlive the batch, so drop their ID strings too; without this the
    # per-batch memory bound only covers the dataclass wrappers. Any later read raises, on purpose.
    for person in persons:
        person._distinct_ids = None
    return deleted


# After this many consecutive per-person failures the fallback stops and marks the rest failed,
# so a systemic outage costs a handful of calls per attempt rather than one per person.
_TRAINING_DELETION_FALLBACK_FAILURE_LIMIT = 3


def _queue_training_deletion_isolating_failures(
    team_id: int,
    persons: builtins.list[Person],
    failures: builtins.list[PersonDeletionFailure],
) -> builtins.list[Person]:
    """Queue training deletion for ``persons`` and return the ones it succeeded for.

    Each call scans replay events for the distinct IDs it is given, so the batch goes out as one
    flattened call. Only when that raises are the persons retried one at a time, which pins the
    failure on the person that causes it instead of blocking the whole batch.
    """
    try:
        queue_person_training_deletion(
            team_id, [distinct_id for person in persons for distinct_id in person.distinct_ids]
        )
        return persons
    except Exception:
        logger.warning(
            "person_deletion.training_deletion_batch_failed",
            team_id=team_id,
            person_count=len(persons),
            reason="retrying per person to isolate the failure",
        )

    queued: builtins.list[Person] = []
    consecutive_failures = 0
    for index, person in enumerate(persons):
        try:
            queue_person_training_deletion(team_id, person.distinct_ids)
        except Exception as exc:
            consecutive_failures += 1
            gave_up = consecutive_failures >= _TRAINING_DELETION_FALLBACK_FAILURE_LIMIT
            _record_step_failure(
                failures,
                step=PersonDeletionStep.QUEUE_TRAINING_DELETION,
                team_id=team_id,
                exc=exc,
                person_uuids=[p.uuid for p in (persons[index:] if gave_up else [person])],
            )
            if gave_up:
                break
            continue
        consecutive_failures = 0
        queued.append(person)
    return queued


def _run_queued_deletion_steps(
    team_id: int,
    persons: builtins.list[Person],
    distinct_ids_by_person: dict[int, builtins.list[DistinctIdForPerson]],
    failures: builtins.list[PersonDeletionFailure],
    options: _QueuedDeletionOptions,
) -> int:
    """Run the requested steps for persons whose distinct IDs are loaded; returns how many were deleted.

    A person that fails a step is left out of every later step, so a retry redoes that person
    alone.
    """
    eligible = list(persons)
    if options.delete_profile or options.delete_recordings:
        eligible = _queue_training_deletion_isolating_failures(team_id, eligible, failures)
    if options.delete_recordings and eligible:
        try:
            queue_person_recording_deletion(team_id, eligible, actor=options.actor, queue_ai_training_deletion=False)
        except Exception as exc:
            _record_step_failure(
                failures,
                step=PersonDeletionStep.QUEUE_RECORDING_DELETION,
                team_id=team_id,
                exc=exc,
                person_uuids=[person.uuid for person in eligible],
            )
            eligible = []

    if not options.delete_profile or not eligible:
        return 0
    skipped = len(persons) - len(eligible)
    if skipped:
        logger.warning(
            "person_deletion.profile_delete_skipped",
            team_id=team_id,
            person_count=skipped,
            reason="a step before the profile delete failed; those persons stay for the retry",
        )

    result = _tombstone_and_delete_persons(
        team_id,
        eligible,
        lambda person: distinct_ids_by_person[person.pk],
        actor=options.actor,
        was_impersonated=options.was_impersonated,
        organization_id=options.organization_id,
    )
    failures.extend(result.failures)
    return result.deleted_count


def _tombstone_and_delete_persons(
    team_id: int,
    persons: builtins.list[Person],
    distinct_ids_for: Callable[[Person], builtins.list[DistinctIdForPerson] | None],
    *,
    actor: User | None,
    was_impersonated: bool,
    organization_id: uuid_lib.UUID | None,
) -> PersonProfileDeletionResult:
    """Tombstone each person in ClickHouse, batch-delete the survivors from Postgres, then log the deletions.

    The activity log is written last so that a failed Postgres delete followed by a retry
    does not produce duplicate log rows (and the CDP events they fan out to). Logging needs
    an ``organization_id``; a missing ``actor`` (for example a user removed before a queued
    task ran) still records the deletion, with no user attached. A failed log write is
    recorded as its own step rather than raised: the persons are already gone by then, so
    raising would hide a completed deletion behind an error.
    """
    deleted: builtins.list[Person] = []
    failures: builtins.list[PersonDeletionFailure] = []
    for person in persons:
        try:
            delete_person(person=person, distinct_ids=distinct_ids_for(person))
            deleted.append(person)
        except Exception as exc:
            _record_step_failure(
                failures,
                step=PersonDeletionStep.TOMBSTONE_CLICKHOUSE,
                team_id=team_id,
                exc=exc,
                person_uuids=[person.uuid],
            )

    if deleted:
        try:
            delete_persons_from_postgres(team_id, deleted)
        except Exception as exc:
            _record_step_failure(
                failures,
                step=PersonDeletionStep.DELETE_POSTGRES,
                team_id=team_id,
                exc=exc,
                person_uuids=[person.uuid for person in deleted],
            )
            deleted = []

    if organization_id is not None and deleted:
        try:
            # Person reads are eventually consistent, so a retry can resolve and delete a person
            # that an earlier attempt already removed. Skip persons that already have a deleted
            # entry so the audit trail does not record the same deletion twice.
            already_logged = set(
                ActivityLog.objects.filter(
                    team_id=team_id,
                    scope="Person",
                    activity="deleted",
                    item_id__in=[str(person.pk) for person in deleted],
                ).values_list("item_id", flat=True)
            )
            bulk_log_activity(
                [
                    LogActivityEntry(
                        organization_id=organization_id,
                        team_id=team_id,
                        user=actor,
                        was_impersonated=was_impersonated,
                        item_id=person.pk,
                        scope="Person",
                        activity="deleted",
                        detail=Detail(name=str(person.uuid)),
                    )
                    for person in deleted
                    if str(person.pk) not in already_logged
                ]
            )
        except Exception as exc:
            _record_step_failure(
                failures,
                step=PersonDeletionStep.LOG_ACTIVITY,
                team_id=team_id,
                exc=exc,
                person_uuids=[person.uuid for person in deleted],
            )

    return PersonProfileDeletionResult(deleted_count=len(deleted), failures=failures)


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
