"""Find persons whose ClickHouse rows disagree with the persons database.

The persons database, read through personhog, is the source of truth. Scans only read.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models.person.util import _batched_get_persons_by_uuids
from posthog.personhog_client.client import personhog_call
from posthog.personhog_client.proto import ReadOptions

PersonDivergenceKind = Literal["hidden", "swept", "stale"]

# The legacy delete path wrote ClickHouse tombstones at version + 100, so those rows sit at 100 or above.
LEGACY_TOMBSTONE_MIN_VERSION = 100

HIDDEN_TEAM_STEP = 10_000
SWEPT_TEAM_STEP = 10_000
STALE_TEAM_STEP = 5_000

_HIDDEN_SETTINGS = {"max_execution_time": 900, "max_memory_usage": 32_000_000_000}
_SWEPT_SETTINGS = {"apply_deleted_mask": 0, "max_execution_time": 1800, "max_memory_usage": 64_000_000_000}
_STALE_SETTINGS = {
    "max_execution_time": 1800,
    "max_memory_usage": 48_000_000_000,
    "max_bytes_before_external_group_by": 20_000_000_000,
}

# A scan reads only these fields, which keeps person properties out of the RPC payloads.
_VERSION_ONLY_READ_OPTIONS = ReadOptions(field_mask=["id", "uuid", "team_id", "version"])


@frozen
class DivergentPerson:
    team_id: int
    person_uuid: str
    kind: PersonDivergenceKind
    ch_max_version: int
    pg_version: int


@frozen
class ScanSummary:
    candidates: int
    divergent: int
    skipped_team_ids: list[int]


# ── ClickHouse and personhog access ──────────────────────────────────


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


def _resolve_max_team_id(max_team_id: int | None) -> int:
    if max_team_id is not None:
        return max_team_id
    [[highest]] = _ch("SELECT max(team_id) FROM person", {}, _HIDDEN_SETTINGS)
    return int(highest or 0) + 1


# ── Scans over team ranges ───────────────────────────────────────────


def _scan_team_ranges(
    query: Callable[[int, int], list[Any]],
    *,
    min_team_id: int,
    max_team_id: int,
    team_step: int,
    on_rows: Callable[[list[Any]], None],
    log: Callable[[str], None],
) -> list[int]:
    """Return each team that runs out of memory or time even when scanned alone, so the caller can rerun it with higher limits."""
    skipped: list[int] = []

    def scan(lo: int, hi: int) -> None:
        try:
            rows = query(lo, hi)
        except (ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut) as exc:
            reason = "out of memory" if isinstance(exc, ClickHouseQueryMemoryLimitExceeded) else "timed out"
            if hi - lo == 1:
                log(f"team {lo}: {reason}, skipped")
                skipped.append(lo)
                return
            mid = (lo + hi) // 2
            log(f"teams [{lo}, {hi}): {reason}, bisecting")
            scan(lo, mid)
            scan(mid, hi)
            return
        on_rows(rows)
        log(f"teams [{lo}, {hi}): {len(rows)} ClickHouse candidates")

    for lo in range(min_team_id, max_team_id, team_step):
        scan(lo, min(lo + team_step, max_team_id))
    return skipped


def _scan_divergent_persons(
    *,
    sql: str,
    settings: dict[str, int],
    extra_args: dict[str, Any],
    kind: PersonDivergenceKind,
    divergent: Callable[[int, int], bool],
    min_team_id: int,
    max_team_id: int | None,
    team_step: int,
    on_found: Callable[[DivergentPerson], None],
    log: Callable[[str], None],
) -> ScanSummary:
    candidates = 0
    found = 0

    def on_rows(rows: list[Any]) -> None:
        nonlocal candidates, found
        by_team: dict[int, dict[str, int]] = defaultdict(dict)
        for team_id, person_uuid, ch_max_version in rows:
            by_team[int(team_id)][person_uuid] = int(ch_max_version)
        for team_id, ch_versions in sorted(by_team.items()):
            candidates += len(ch_versions)
            pg_versions = _live_person_versions(team_id, list(ch_versions), f"person_divergence_scan_{kind}")
            for person_uuid, pg_version in pg_versions.items():
                ch_max_version = ch_versions[person_uuid]
                if not divergent(pg_version, ch_max_version):
                    continue
                on_found(
                    DivergentPerson(
                        team_id=team_id,
                        person_uuid=person_uuid,
                        kind=kind,
                        ch_max_version=ch_max_version,
                        pg_version=pg_version,
                    )
                )
                found += 1

    skipped = _scan_team_ranges(
        lambda lo, hi: _ch(sql, {"min_team_id": lo, "max_team_id": hi, **extra_args}, settings),
        min_team_id=min_team_id,
        max_team_id=_resolve_max_team_id(max_team_id),
        team_step=team_step,
        on_rows=on_rows,
        log=log,
    )
    return ScanSummary(candidates=candidates, divergent=found, skipped_team_ids=skipped)


_HIDDEN_SQL = """
SELECT team_id, toString(id), max(version) AS max_version
FROM person
WHERE team_id >= %(min_team_id)s AND team_id < %(max_team_id)s
    AND (team_id, id) IN (
        SELECT team_id, id FROM person
        WHERE team_id >= %(min_team_id)s AND team_id < %(max_team_id)s
            AND is_deleted = 1 AND version >= %(min_tombstone_version)s
    )
GROUP BY team_id, id
HAVING argMax(is_deleted, version) = 1 AND max_version >= %(min_tombstone_version)s
"""


def scan_hidden_persons(
    *,
    min_team_id: int = 0,
    max_team_id: int | None = None,
    team_step: int = HIDDEN_TEAM_STEP,
    on_found: Callable[[DivergentPerson], None],
    log: Callable[[str], None],
) -> ScanSummary:
    """Persons live in Postgres whose newest ClickHouse row is a legacy (version 100 or above) tombstone.

    Run it, then repair what it finds, right before every ClickHouse deletion sweep while such
    tombstones remain: the sweep deletes every ClickHouse row of these persons.
    """
    return _scan_divergent_persons(
        sql=_HIDDEN_SQL,
        settings=_HIDDEN_SETTINGS,
        extra_args={"min_tombstone_version": LEGACY_TOMBSTONE_MIN_VERSION},
        kind="hidden",
        divergent=lambda _pg_version, _ch_max_version: True,
        min_team_id=min_team_id,
        max_team_id=max_team_id,
        team_step=team_step,
        on_found=on_found,
        log=log,
    )


# The ClickHouse deletion sweep deletes every row of a person whose highest-version row is a tombstone.
# That includes a live row written after the tombstone at a lower version, so the person stays live in
# Postgres with no visible ClickHouse row.
_SWEPT_SQL = """
SELECT team_id, toString(id), max(version) AS max_version
FROM person
WHERE team_id >= %(min_team_id)s AND team_id < %(max_team_id)s
    AND (team_id, id) IN (
        SELECT team_id, id FROM person
        WHERE team_id >= %(min_team_id)s AND team_id < %(max_team_id)s
            AND NOT _row_exists AND is_deleted = 1 AND version >= %(min_tombstone_version)s
    )
GROUP BY team_id, id
HAVING countIf(_row_exists) = 0
    AND maxIf(_timestamp, is_deleted = 0) > maxIf(_timestamp, is_deleted = 1 AND version >= %(min_tombstone_version)s)
"""


def scan_swept_persons(
    *,
    min_team_id: int = 0,
    max_team_id: int | None = None,
    team_step: int = SWEPT_TEAM_STEP,
    on_found: Callable[[DivergentPerson], None],
    log: Callable[[str], None],
) -> ScanSummary:
    """Live Postgres persons with every ClickHouse row deleted, including a live row written after a legacy tombstone.

    Run it soon after a ClickHouse deletion sweep: once merges remove the deleted rows, no scan finds the person.
    """
    return _scan_divergent_persons(
        sql=_SWEPT_SQL,
        settings=_SWEPT_SETTINGS,
        extra_args={"min_tombstone_version": LEGACY_TOMBSTONE_MIN_VERSION},
        kind="swept",
        divergent=lambda _pg_version, _ch_max_version: True,
        min_team_id=min_team_id,
        max_team_id=max_team_id,
        team_step=team_step,
        on_found=on_found,
        log=log,
    )


# A row with a lower version that arrives well after the winning row means Postgres restarted the
# person below ClickHouse, so every later update loses to the old winner.
_STALE_SQL = """
SELECT team_id, toString(id), max(version) AS max_version
FROM person
WHERE team_id >= %(min_team_id)s AND team_id < %(max_team_id)s
    AND (team_id, id) IN (
        SELECT team_id, id FROM person
        WHERE team_id >= %(min_team_id)s AND team_id < %(max_team_id)s
            AND _timestamp > now() - toIntervalDay(%(window_days)s)
    )
GROUP BY team_id, id
HAVING argMax(is_deleted, version) = 0
    AND argMax(version, _timestamp) < max_version
    AND max(_timestamp) > argMax(_timestamp, version) + INTERVAL 1 HOUR
"""


def scan_stale_persons(
    *,
    window_days: int,
    min_team_id: int = 0,
    max_team_id: int | None = None,
    team_step: int = STALE_TEAM_STEP,
    on_found: Callable[[DivergentPerson], None],
    log: Callable[[str], None],
) -> ScanSummary:
    """Persons whose live ClickHouse winner outranks Postgres, found through a late lower-version row."""
    return _scan_divergent_persons(
        sql=_STALE_SQL,
        settings=_STALE_SETTINGS,
        extra_args={"window_days": window_days},
        kind="stale",
        divergent=lambda pg_version, ch_max_version: pg_version < ch_max_version,
        min_team_id=min_team_id,
        max_team_id=max_team_id,
        team_step=team_step,
        on_found=on_found,
        log=log,
    )
