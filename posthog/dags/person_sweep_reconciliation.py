"""Postgres side of the deletion sweep's reconciliation checkpoint.

The sweep snapshots persons and distinct ids whose newest ClickHouse version is deleted. ClickHouse
can hide a key that is live in Postgres: person UUIDs derive from the distinct id, so a person
recreated after a legacy hard delete restarts at a low version, below the version + 100 tombstone
that delete published. This module finds the snapshot keys that are live in Postgres, so the
sweep can exclude them, and republishes them so ClickHouse shows them again.
"""

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context, copy_context
from typing import TypeVar
from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.models.person import Person
from posthog.models.person.util import (
    PERSONHOG_BATCH_SIZE,
    _batched_get_persons_by_distinct_ids,
    _batched_get_persons_by_uuids,
    create_person,
    create_person_distinct_id,
    get_person_tombstones,
)
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.converters import proto_person_to_model
from posthog.personhog_client.proto import (
    ReadOptions,
    SetPersonDistinctIdVersionFloorRequest,
    SetPersonVersionFloorRequest,
)

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")
_R = TypeVar("_R")

# The liveness pass touches every snapshot key, so it reads identity fields only and leaves the
# property blobs in Postgres. Only the persons it republishes are read in full.
_PERSON_LIVENESS_FIELDS = ReadOptions(field_mask=["id", "uuid", "team_id", "version"])
_MAPPING_LIVENESS_FIELDS = ReadOptions(field_mask=["id", "uuid", "team_id"])

# The floor RPC writes the primary, and the read-back comes from a replica. A person the replica
# still shows below the floor is left excluded and unpublished, and the next sweep retries it.
REPLICA_CATCH_UP_ATTEMPTS = 3
REPLICA_CATCH_UP_SECONDS = 1.0


@frozen
class LivePerson:
    """A snapshot person that Postgres holds live."""

    uuid: str
    person_id: int


@frozen
class PersonHead:
    """The newest ClickHouse version of a person."""

    max_version: int
    is_deleted: bool


@frozen
class MappingHead:
    """The newest ClickHouse version of a distinct id mapping."""

    max_version: int
    is_deleted: bool
    person_uuid: str


@frozen(frozen=False)
class RepublishOutcome:
    republished: int = 0
    skipped: int = 0


def _fan_out(fn: Callable[[_T], _R], chunks: Sequence[_T], concurrency: int) -> list[_R]:
    """Call fn once per chunk, at most `concurrency` at a time, and return results in chunk order.

    Any failure propagates, so a caller never acts on a partial lookup.
    """
    if concurrency <= 1 or len(chunks) <= 1:
        return [fn(chunk) for chunk in chunks]

    # ThreadPoolExecutor does not inherit contextvars, which carry the personhog caller tag, so each
    # task runs in a copy of the calling thread's context.
    def in_context(task: tuple[Context, _T]) -> _R:
        context, chunk = task
        return context.run(fn, chunk)

    with ThreadPoolExecutor(max_workers=min(concurrency, len(chunks)), thread_name_prefix="sweep-reconcile") as pool:
        return list(pool.map(in_context, [(copy_context(), chunk) for chunk in chunks]))


def _chunks(items: Sequence[_T]) -> list[list[_T]]:
    return [list(items[i : i + PERSONHOG_BATCH_SIZE]) for i in range(0, len(items), PERSONHOG_BATCH_SIZE)]


class PostgresReconciler:
    """Reads snapshot keys back from Postgres through personhog, and republishes the live ones.

    Republishing raises the Postgres version above every ClickHouse version of the key first, then
    publishes the row at the version Postgres holds. The order matters: a row published above the
    Postgres version would hide every later ingestion update, because ingestion publishes at the
    Postgres version and ClickHouse keeps the highest one.
    """

    def __init__(self, *, concurrency: int, dry_run: bool) -> None:
        self.concurrency = concurrency
        self.dry_run = dry_run

    def live_persons(self, team_id: int, uuids: Sequence[str]) -> list[LivePerson]:
        def lookup(chunk: list[str]) -> list[LivePerson]:
            persons = _batched_get_persons_by_uuids(
                team_id, chunk, "sweep_reconcile_persons", read_options=_PERSON_LIVENESS_FIELDS
            )
            return [LivePerson(uuid=str(UUID(p.uuid)), person_id=p.id) for p in persons]

        results = personhog_call("sweep_reconcile_persons", lambda: _fan_out(lookup, _chunks(uuids), self.concurrency))
        return [person for chunk in results for person in chunk]

    def live_mappings(self, team_id: int, distinct_ids: Sequence[str]) -> dict[str, str]:
        """Map each distinct id that Postgres holds live, with a live person, to that person's UUID."""

        def lookup(chunk: list[str]) -> list[tuple[str, str]]:
            results = _batched_get_persons_by_distinct_ids(
                team_id,
                chunk,
                "sweep_reconcile_distinct_ids",
                deduplicate_by_person=False,
                read_options=_MAPPING_LIVENESS_FIELDS,
            )
            return [(r.distinct_id, str(UUID(r.person.uuid))) for r in results]

        results = personhog_call(
            "sweep_reconcile_distinct_ids", lambda: _fan_out(lookup, _chunks(distinct_ids), self.concurrency)
        )
        return dict(pair for chunk in results for pair in chunk)

    def republish_persons(
        self, team_id: int, persons: Sequence[LivePerson], heads: dict[str, PersonHead]
    ) -> RepublishOutcome:
        outcome = RepublishOutcome()
        # The floor RPC also raises a tombstoned row, and the replica lookup can lag a tombstone.
        # Raising a tombstone's version would detach it from the version its ClickHouse row has.
        tombstoned = self._tombstoned(team_id, [p.uuid for p in persons])
        floors: dict[str, int] = {}
        for person in persons:
            head = heads.get(person.uuid)
            if head is None or not head.is_deleted or person.uuid in tombstoned:
                outcome.skipped += 1
                continue
            floors[person.uuid] = head.max_version + 1
            if not self.dry_run:
                self._set_person_version_floor(team_id, person.person_id, floors[person.uuid])
        if self.dry_run:
            outcome.republished = len(floors)
            return outcome
        if not floors:
            return outcome

        caught_up = self._read_back_persons(team_id, floors)
        # A delete can land between the first check and the floor, so the primary decides again.
        tombstoned = self._tombstoned(team_id, list(caught_up))
        for uuid, (version, row) in caught_up.items():
            if uuid in tombstoned:
                continue
            create_person(
                uuid=uuid,
                team_id=team_id,
                version=version,
                properties=row.properties,
                is_identified=row.is_identified,
                is_deleted=False,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
            )
            outcome.republished += 1
        outcome.skipped += len(floors) - outcome.republished
        return outcome

    def republish_mappings(
        self, team_id: int, owners: dict[str, str], heads: dict[str, MappingHead]
    ) -> RepublishOutcome:
        """Republish each live mapping that ClickHouse hides or points at another person.

        The published version is the floor itself. The floor RPC does not return the version it
        leaves, and a stored version above the floor means Postgres wrote that version after
        ClickHouse's newest row, so its own publish outranks this row. The owner check below makes
        both rows name the same person.
        """
        outcome = RepublishOutcome()
        floored: dict[str, tuple[str, int]] = {}
        for distinct_id, owner in owners.items():
            head = heads.get(distinct_id)
            if head is None or (not head.is_deleted and head.person_uuid == owner):
                outcome.skipped += 1
                continue
            version = head.max_version + 1
            if self.dry_run:
                floored[distinct_id] = (owner, version)
                continue
            person = self._set_distinct_id_version_floor(team_id, distinct_id, version)
            if person is None or str(person.uuid) != owner:
                logger.warning("sweep_reconcile.mapping_moved", team_id=team_id, distinct_id=distinct_id)
                outcome.skipped += 1
                continue
            floored[distinct_id] = (owner, version)
        if self.dry_run:
            outcome.republished = len(floored)
            return outcome
        if not floored:
            return outcome

        tombstoned = self._tombstoned(team_id, sorted({owner for owner, _ in floored.values()}))
        for distinct_id, (owner, version) in floored.items():
            if owner in tombstoned:
                outcome.skipped += 1
                continue
            create_person_distinct_id(
                team_id=team_id, distinct_id=distinct_id, person_id=owner, version=version, is_deleted=False
            )
            outcome.republished += 1
        return outcome

    def _read_back_persons(self, team_id: int, floors: dict[str, int]) -> dict[str, tuple[int, Person]]:
        """Read each floored person from the replica once it shows a version at or above its floor.

        The row then carries properties and version from one Postgres state, so the republished
        row matches what ingestion would publish for that version.
        """
        caught_up: dict[str, tuple[int, Person]] = {}
        pending = dict(floors)
        for attempt in range(REPLICA_CATCH_UP_ATTEMPTS):
            if attempt:
                time.sleep(REPLICA_CATCH_UP_SECONDS)
            persons = personhog_call(
                "sweep_reconcile_read_back",
                lambda: _batched_get_persons_by_uuids(
                    team_id, list(pending), "sweep_reconcile_read_back", concurrency=self.concurrency
                ),
            )
            for proto in persons:
                uuid = str(UUID(proto.uuid))
                if uuid in pending and proto.version >= pending[uuid]:
                    caught_up[uuid] = (proto.version, proto_person_to_model(proto))
                    del pending[uuid]
            if not pending:
                break
        if pending:
            logger.warning("sweep_reconcile.replica_behind", team_id=team_id, persons=len(pending))
        return caught_up

    @staticmethod
    def _tombstoned(team_id: int, uuids: Sequence[str]) -> set[str]:
        """The given persons that the Postgres primary holds tombstoned."""
        if not uuids:
            return set()
        return {str(t.uuid) for t in get_person_tombstones(team_id, [UUID(u) for u in uuids])}

    @staticmethod
    def _set_person_version_floor(team_id: int, person_id: int, version: int) -> None:
        personhog_call(
            "set_person_version_floor",
            lambda: require_personhog_client().set_person_version_floor(
                SetPersonVersionFloorRequest(team_id=team_id, person_id=person_id, min_version=version)
            ),
        )

    @staticmethod
    def _set_distinct_id_version_floor(team_id: int, distinct_id: str, version: int) -> Person | None:
        response = personhog_call(
            "set_person_distinct_id_version_floor",
            lambda: require_personhog_client().set_person_distinct_id_version_floor(
                SetPersonDistinctIdVersionFloorRequest(team_id=team_id, distinct_id=distinct_id, min_version=version)
            ),
        )
        return proto_person_to_model(response.person) if response.HasField("person") else None
