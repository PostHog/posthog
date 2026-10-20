"""ClickHouse and personhog reads shared by the scans and the repair."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar
from uuid import UUID

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.models.person.util import _batched_get_persons_by_uuids, get_person_tombstones
from posthog.personhog_client.client import personhog_call
from posthog.personhog_client.proto import ReadOptions

_T = TypeVar("_T")


# A scan reads only these fields, which keeps person properties out of the RPC payloads.
_VERSION_ONLY_READ_OPTIONS = ReadOptions(field_mask=["id", "uuid", "team_id", "version"])


def _ch(sql: str, args: dict[str, Any], settings: dict[str, int]) -> list[Any]:
    return sync_execute(sql, args, settings=settings, workload=Workload.OFFLINE, readonly=True)


def _live_person_versions(team_id: int, person_uuids: list[str], operation: str) -> dict[str, int]:
    persons = personhog_call(
        operation,
        lambda: _batched_get_persons_by_uuids(
            team_id, person_uuids, operation, read_options=_VERSION_ONLY_READ_OPTIONS
        ),
    )
    return {str(UUID(p.uuid)): int(p.version) for p in persons}


def _tombstoned_uuids(team_id: int, person_uuids: list[str]) -> set[str]:
    if not person_uuids:
        return set()
    return {str(t.uuid) for t in get_person_tombstones(team_id, [UUID(u) for u in person_uuids])}


def _chunks(items: Sequence[_T], size: int) -> list[Sequence[_T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
