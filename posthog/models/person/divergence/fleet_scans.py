"""Fleet-wide divergence scans: hidden, swept, stale and the uniform sample."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models.team import Team

from . import datatypes, lookups

# The legacy delete path wrote ClickHouse tombstones at version + 100, so those rows sit at 100 or above.
LEGACY_TOMBSTONE_MIN_VERSION = 100

HIDDEN_TEAM_STEP = 10_000

SWEPT_TEAM_STEP = 10_000

STALE_TEAM_STEP = 5_000

SAMPLE_TEAM_STEP = 10_000

_HIDDEN_SETTINGS = {"max_execution_time": 900, "max_memory_usage": 32_000_000_000}

_SWEPT_SETTINGS = {"apply_deleted_mask": 0, "max_execution_time": 1800, "max_memory_usage": 64_000_000_000}

_STALE_SETTINGS = {
    "max_execution_time": 1800,
    "max_memory_usage": 48_000_000_000,
    "max_bytes_before_external_group_by": 20_000_000_000,
}

_SAMPLE_SETTINGS = {"max_execution_time": 3600, "max_memory_usage": 32_000_000_000}


def _resolve_max_team_id(max_team_id: int | None) -> int:
    if max_team_id is not None:
        return max_team_id
    [[highest]] = lookups._ch("SELECT max(team_id) FROM person", {}, _HIDDEN_SETTINGS)
    return int(highest or 0) + 1


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
    kind: datatypes.PersonDivergenceKind,
    divergent: Callable[[int, int], bool],
    min_team_id: int,
    max_team_id: int | None,
    team_step: int,
    on_found: Callable[[datatypes.DivergentPerson], None],
    log: Callable[[str], None],
) -> datatypes.ScanSummary:
    candidates = 0
    found = 0

    def on_rows(rows: list[Any]) -> None:
        nonlocal candidates, found
        by_team: dict[int, dict[str, int]] = defaultdict(dict)
        for team_id, person_uuid, ch_max_version in rows:
            by_team[int(team_id)][person_uuid] = int(ch_max_version)
        for team_id, ch_versions in sorted(by_team.items()):
            candidates += len(ch_versions)
            pg_versions = lookups._live_person_versions(team_id, list(ch_versions), f"person_divergence_scan_{kind}")
            for person_uuid, pg_version in pg_versions.items():
                ch_max_version = ch_versions[person_uuid]
                if not divergent(pg_version, ch_max_version):
                    continue
                on_found(
                    datatypes.DivergentPerson(
                        team_id=team_id,
                        person_uuid=person_uuid,
                        kind=kind,
                        ch_max_version=ch_max_version,
                        pg_version=pg_version,
                    )
                )
                found += 1

    skipped = _scan_team_ranges(
        lambda lo, hi: lookups._ch(sql, {"min_team_id": lo, "max_team_id": hi, **extra_args}, settings),
        min_team_id=min_team_id,
        max_team_id=_resolve_max_team_id(max_team_id),
        team_step=team_step,
        on_rows=on_rows,
        log=log,
    )
    return datatypes.ScanSummary(candidates=candidates, divergent=found, skipped_team_ids=skipped)


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
    on_found: Callable[[datatypes.DivergentPerson], None],
    log: Callable[[str], None],
) -> datatypes.ScanSummary:
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
    on_found: Callable[[datatypes.DivergentPerson], None],
    log: Callable[[str], None],
) -> datatypes.ScanSummary:
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
    on_found: Callable[[datatypes.DivergentPerson], None],
    log: Callable[[str], None],
) -> datatypes.ScanSummary:
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


_SAMPLE_SQL = """
SELECT team_id, toString(id), max(version) AS max_version, toUnixTimestamp(argMax(_timestamp, version)) AS written_at
FROM person
WHERE cityHash64(id) %% %(modulus)s = %(residue)s AND team_id >= %(min_team_id)s AND team_id < %(max_team_id)s
GROUP BY team_id, id
HAVING argMax(is_deleted, version) = 0
    AND (%(written_within_days)s = 0 OR argMax(_timestamp, version) >= now() - toIntervalDay(%(written_within_days)s))
"""


def _classify_sampled(
    pg_version: int | None, ch_max_version: int, *, team_exists: bool, tombstoned: bool
) -> datatypes.SampleClassification:
    if not team_exists:
        return "team_gone"
    if pg_version is None:
        return "pg_tombstone" if tombstoned else "pg_absent"
    if pg_version == ch_max_version:
        return "equal"
    return "pg_below_ch" if pg_version < ch_max_version else "pg_above_ch"


def scan_sample(
    *,
    modulus: int,
    residue: int,
    written_within_days: int | None = None,
    cutoff: datetime | None = None,
    min_team_id: int = 0,
    max_team_id: int | None = None,
    team_step: int = SAMPLE_TEAM_STEP,
    on_sampled: Callable[[datatypes.SampledPerson], None],
    log: Callable[[str], None],
) -> datatypes.SampleSummary:
    """Classify a uniform sample of live ClickHouse persons against Postgres."""
    if not 0 <= residue < modulus:
        raise ValueError("residue must be in [0, modulus)")
    cutoff_ts = cutoff.timestamp() if cutoff is not None else None
    counts: Counter[datatypes.SampleBucket] = Counter()
    sampled_count = 0

    def query(lo: int, hi: int) -> list[Any]:
        return lookups._ch(
            _SAMPLE_SQL,
            {
                "modulus": modulus,
                "residue": residue,
                "written_within_days": written_within_days or 0,
                "min_team_id": lo,
                "max_team_id": hi,
            },
            _SAMPLE_SETTINGS,
        )

    def on_rows(rows: list[Any]) -> None:
        nonlocal sampled_count
        if not rows:
            return
        sampled_count += len(rows)
        by_team: dict[int, dict[str, tuple[int, datatypes.SampleEra]]] = defaultdict(dict)
        for team_id, person_uuid, ch_max_version, written_at in rows:
            era: datatypes.SampleEra = (
                "any" if cutoff_ts is None else "before_cutoff" if written_at < cutoff_ts else "since_cutoff"
            )
            by_team[int(team_id)][person_uuid] = (int(ch_max_version), era)

        existing_teams = set(Team.objects.filter(id__in=list(by_team)).values_list("id", flat=True))
        for team_id, sampled in sorted(by_team.items()):
            team_exists = team_id in existing_teams
            # A deleted team's persons can outlive it in Postgres, so they are team_gone whatever their version.
            pg_versions = (
                lookups._live_person_versions(team_id, list(sampled), "person_divergence_sample") if team_exists else {}
            )
            missing = [u for u in sampled if u not in pg_versions]
            tombstoned = lookups._tombstoned_uuids(team_id, missing) if team_exists else set()
            for person_uuid, (ch_max_version, era) in sampled.items():
                pg_version = pg_versions.get(person_uuid)
                classification = _classify_sampled(
                    pg_version, ch_max_version, team_exists=team_exists, tombstoned=person_uuid in tombstoned
                )
                counts[datatypes.SampleBucket(classification=classification, era=era)] += 1
                on_sampled(
                    datatypes.SampledPerson(
                        team_id=team_id,
                        person_uuid=person_uuid,
                        classification=classification,
                        era=era,
                        ch_max_version=ch_max_version,
                        pg_version=pg_version,
                    )
                )

    skipped = _scan_team_ranges(
        query,
        min_team_id=min_team_id,
        max_team_id=_resolve_max_team_id(max_team_id),
        team_step=team_step,
        on_rows=on_rows,
        log=log,
    )
    log(f"sampled {sampled_count} live ClickHouse persons")
    return datatypes.SampleSummary(sampled=sampled_count, counts=dict(counts), skipped_team_ids=skipped)
