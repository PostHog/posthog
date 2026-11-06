"""ClickHouse and personhog reads shared by the scans and the repair."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.models.person.util import (
    _batched_get_distinct_ids_for_persons,
    _batched_get_persons_by_uuids,
    get_person_tombstones,
)
from posthog.personhog_client.client import personhog_call
from posthog.personhog_client.proto import ReadOptions

if TYPE_CHECKING:
    from personhog.types.v1 import person_pb2

_T = TypeVar("_T")


# A scan reads only these fields, which keeps person properties out of the RPC payloads.
_VERSION_ONLY_READ_OPTIONS = ReadOptions(field_mask=["id", "uuid", "team_id", "version"])


def _ch(sql: str, args: dict[str, Any], settings: dict[str, int]) -> list[Any]:
    return sync_execute(sql, args, settings=settings, workload=Workload.OFFLINE, readonly=True)


def _live_persons(team_id: int, person_uuids: list[str], operation: str) -> list[person_pb2.Person]:
    return personhog_call(
        operation,
        lambda: _batched_get_persons_by_uuids(
            team_id, person_uuids, operation, read_options=_VERSION_ONLY_READ_OPTIONS
        ),
    )


def _live_person_versions(team_id: int, person_uuids: list[str], operation: str) -> dict[str, int]:
    return {str(UUID(p.uuid)): int(p.version) for p in _live_persons(team_id, person_uuids, operation)}


def _tombstoned_uuids(team_id: int, person_uuids: list[str]) -> set[str]:
    if not person_uuids:
        return set()
    return {str(t.uuid) for t in get_person_tombstones(team_id, [UUID(u) for u in person_uuids])}


def _chunks(items: Sequence[_T], size: int) -> list[Sequence[_T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _live_distinct_ids_for_persons(team_id: int, person_ids: list[int]) -> dict[int, list[tuple[str, int]]]:
    """Each person's live distinct ids with their versions."""
    if not person_ids:
        return {}
    by_person = personhog_call(
        "get_distinct_ids_for_persons", lambda: _batched_get_distinct_ids_for_persons(team_id, person_ids)
    )
    return {person_id: [(d.id, d.version) for d in dids] for person_id, dids in by_person.items()}
