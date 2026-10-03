"""Postgres side of the deletion sweep's reconciliation checkpoint.

The sweep snapshots persons and distinct ids whose newest ClickHouse version is deleted, then
deletes every ClickHouse row of each key up to the newest version it saw, M. Postgres is the only
version authority, so every snapshot key is checked against it first:

- A key that Postgres holds live is excluded from the run. ClickHouse can hide a live key: person
  UUIDs derive from the distinct id, so a person recreated after a legacy hard delete restarts
  below the version + 100 tombstone that delete published.
- A key that Postgres holds as a tombstone at M or above needs nothing. A revival writes above M,
  so ClickHouse sees it, and the delete's version bound keeps its row.
- Any other key, absent from Postgres or tombstoned below M, gets a Postgres tombstone at M on the
  primary. After that, every later write to the key lands above M too. The primary reports a key
  that is live after all, and that key is excluded.

A key whose check cannot finish is excluded, so a failure spares keys rather than deletes them.
"""

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context, copy_context
from dataclasses import fields
from functools import partial
from typing import TypeVar
from uuid import UUID

import grpc
import structlog

from posthog.dataclasses import frozen
from posthog.models.person.util import (
    PERSONHOG_BATCH_SIZE,
    DistinctIdVersionFloor,
    DistinctIdVersionHead,
    PersonVersionFloor,
    PersonVersionHead,
    VersionFloorOutcome,
    ensure_distinct_id_version_floors,
    ensure_person_version_floors,
    get_distinct_id_version_heads,
    get_person_version_heads,
)

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")
_R = TypeVar("_R")

FLOOR_ATTEMPTS = 3
FLOOR_RETRY_BACKOFF_SECONDS = 1.0


@frozen
class PersonKey:
    """A snapshot person and the newest ClickHouse version the snapshot saw."""

    uuid: UUID
    max_version: int


@frozen
class MappingKey:
    """A snapshot distinct id, with the owner and version of its newest ClickHouse row."""

    distinct_id: str
    # Owns the tombstone written where Postgres has no row for the distinct id.
    person_uuid: UUID
    max_version: int


@frozen
class ReconcileTally:
    live: int = 0
    # Postgres holds the mapping live, but its person has no row.
    orphaned_live: int = 0
    current: int = 0
    floored: int = 0
    floor_failed: int = 0
    floor_capped: int = 0
    # A dry run skips the floor write. It deletes nothing, so the key needs no exclusion.
    floor_skipped: int = 0

    def __add__(self, other: "ReconcileTally") -> "ReconcileTally":
        return ReconcileTally(**{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)})

    @property
    def excluded(self) -> int:
        return self.live + self.orphaned_live + self.floor_failed + self.floor_capped


@frozen
class TeamReconciliation:
    """One team's checked keys: the ones to exclude from the run, and how each key resolved."""

    excluded: list[str]
    tally: ReconcileTally


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


def _with_retries(fn: Callable[[], _T]) -> _T:
    """Call fn, retrying an RPC failure a bounded number of times. Other errors propagate at once."""
    for attempt in range(1, FLOOR_ATTEMPTS):
        try:
            return fn()
        except grpc.RpcError:
            time.sleep(FLOOR_RETRY_BACKOFF_SECONDS * attempt)
    return fn()


class PostgresReconciler:
    """Checks snapshot keys against Postgres through personhog, and floors the ones that need it.

    It reads every key from a replica, which returns tombstones too. Only keys the replica shows
    absent or tombstoned below M go to the primary. The floor writes never touch a live row.
    """

    def __init__(self, *, concurrency: int, dry_run: bool, max_floor_keys: int) -> None:
        self.concurrency = concurrency
        self.dry_run = dry_run
        # Shared by persons and mappings, so it bounds the run's whole write load on the primary.
        self.floor_budget = max_floor_keys

    def persons(self, team_id: int, keys: Sequence[PersonKey]) -> TeamReconciliation:
        heads: dict[UUID, PersonVersionHead] = {
            head.uuid: head
            for chunk in _fan_out(
                partial(get_person_version_heads, team_id), _chunks([k.uuid for k in keys]), self.concurrency
            )
            for head in chunk
        }
        excluded: list[str] = []
        tally = ReconcileTally()
        to_floor: list[PersonKey] = []
        for key in keys:
            head = heads.get(key.uuid)
            if head is not None and not head.is_deleted:
                excluded.append(str(key.uuid))
                tally += ReconcileTally(live=1)
            elif head is not None and head.version >= key.max_version:
                tally += ReconcileTally(current=1)
            else:
                to_floor.append(key)

        def floor(chunk: list[PersonKey]) -> TeamReconciliation:
            results = {
                r.uuid: r
                for r in ensure_person_version_floors(
                    team_id, [PersonVersionFloor(uuid=k.uuid, min_version=k.max_version) for k in chunk]
                )
            }
            chunk_excluded: list[str] = []
            chunk_tally = ReconcileTally()
            for key in chunk:
                result = results.get(key.uuid)
                if result is not None and result.outcome is VersionFloorOutcome.LIVE:
                    chunk_excluded.append(str(key.uuid))
                    chunk_tally += ReconcileTally(live=1)
                elif result is None or result.version < key.max_version:
                    logger.error("sweep_reconcile.floor_not_held", team_id=team_id, kind="persons")
                    chunk_excluded.append(str(key.uuid))
                    chunk_tally += ReconcileTally(floor_failed=1)
                else:
                    chunk_tally += ReconcileTally(floored=1)
            return TeamReconciliation(excluded=chunk_excluded, tally=chunk_tally)

        floored = self._floor(team_id, "persons", to_floor, lambda key: str(key.uuid), floor)
        return TeamReconciliation(excluded=excluded + floored.excluded, tally=tally + floored.tally)

    def mappings(self, team_id: int, keys: Sequence[MappingKey]) -> TeamReconciliation:
        heads: dict[str, DistinctIdVersionHead] = {
            head.distinct_id: head
            for chunk in _fan_out(
                partial(get_distinct_id_version_heads, team_id),
                _chunks([k.distinct_id for k in keys]),
                self.concurrency,
            )
            for head in chunk
        }
        excluded: list[str] = []
        tally = ReconcileTally()
        to_floor: list[MappingKey] = []
        for key in keys:
            head = heads.get(key.distinct_id)
            if head is not None and not head.is_deleted:
                excluded.append(key.distinct_id)
                tally += ReconcileTally(live=1) if head.person_uuid else ReconcileTally(orphaned_live=1)
            elif head is not None and head.version >= key.max_version:
                tally += ReconcileTally(current=1)
            else:
                to_floor.append(key)

        def floor(chunk: list[MappingKey]) -> TeamReconciliation:
            results = {
                r.distinct_id: r
                for r in ensure_distinct_id_version_floors(
                    team_id,
                    [
                        DistinctIdVersionFloor(
                            distinct_id=k.distinct_id, min_version=k.max_version, person_uuid=k.person_uuid
                        )
                        for k in chunk
                    ],
                )
            }
            chunk_excluded: list[str] = []
            chunk_tally = ReconcileTally()
            for key in chunk:
                result = results.get(key.distinct_id)
                if result is not None and result.outcome is VersionFloorOutcome.LIVE:
                    chunk_excluded.append(key.distinct_id)
                    chunk_tally += ReconcileTally(live=1) if result.person_uuid else ReconcileTally(orphaned_live=1)
                elif result is None or result.version < key.max_version:
                    logger.error("sweep_reconcile.floor_not_held", team_id=team_id, kind="distinct_ids")
                    chunk_excluded.append(key.distinct_id)
                    chunk_tally += ReconcileTally(floor_failed=1)
                else:
                    chunk_tally += ReconcileTally(floored=1)
            return TeamReconciliation(excluded=chunk_excluded, tally=chunk_tally)

        floored = self._floor(team_id, "distinct_ids", to_floor, lambda key: key.distinct_id, floor)
        return TeamReconciliation(excluded=excluded + floored.excluded, tally=tally + floored.tally)

    def _floor(
        self,
        team_id: int,
        kind: str,
        keys: Sequence[_T],
        key_name: Callable[[_T], str],
        floor: Callable[[list[_T]], TeamReconciliation],
    ) -> TeamReconciliation:
        """Floor keys on the primary one batch at a time, serially, within the run's budget.

        A batch that keeps failing, or that the budget does not cover, is excluded whole: the
        failed call can have committed part of the batch, so no result in it can be trusted.
        """
        excluded: list[str] = []
        tally = ReconcileTally()
        if self.dry_run:
            return TeamReconciliation(excluded=[], tally=ReconcileTally(floor_skipped=len(keys)))
        for chunk in _chunks(keys):
            allowed = chunk[: max(self.floor_budget, 0)]
            if len(allowed) < len(chunk):
                excluded.extend(key_name(key) for key in chunk[len(allowed) :])
                tally += ReconcileTally(floor_capped=len(chunk) - len(allowed))
            if not allowed:
                continue
            self.floor_budget -= len(allowed)
            try:
                result = _with_retries(partial(floor, allowed))
            except grpc.RpcError:
                logger.warning(
                    "sweep_reconcile.floor_failed", team_id=team_id, kind=kind, keys=len(allowed), exc_info=True
                )
                excluded.extend(key_name(key) for key in allowed)
                tally += ReconcileTally(floor_failed=len(allowed))
                continue
            excluded.extend(result.excluded)
            tally += result.tally
        return TeamReconciliation(excluded=excluded, tally=tally)
