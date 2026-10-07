"""Find and repair persons whose ClickHouse rows disagree with the persons database.

The persons database, read through personhog, is the source of truth. Scans only read. A repair
republishes the Postgres state of a person and its distinct ids to ClickHouse. When ClickHouse
holds a version at or above the Postgres one, the repair first raises the Postgres version above
it, so the published row wins and the next ingestion update still outranks it.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import field
from typing import Any, Literal, TypeVar
from uuid import UUID

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.routing import flush_all_producers
from posthog.kafka_client.topics import KAFKA_PERSON
from posthog.models.person import Person
from posthog.models.person.sql import INSERT_PERSON_SQL
from posthog.models.person.util import (
    _batched_get_distinct_ids_for_persons,
    _batched_get_persons_by_uuids,
    _person_row,
    create_person_distinct_id,
    get_person_tombstones,
    get_persons_by_uuids,
)
from posthog.models.team import Team
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import (
    CONSISTENCY_LEVEL_STRONG,
    GetDistinctIdsForPersonsRequest,
    ReadOptions,
    SetPersonDistinctIdVersionFloorRequest,
    SetPersonVersionFloorRequest,
)

PersonDivergenceKind = Literal["hidden", "swept", "stale", "behind", "absent"]
MappingDivergenceKind = Literal["hidden", "other_person", "stale", "absent"]
RepairOutcome = Literal[
    "would_repair",
    "repaired",
    "skipped_not_divergent",
    "skipped_not_live",
    "skipped_team_gone",
    "skipped_tombstoned",
    "skipped_owner_changed",
    "skipped_mapping_gone",
    "skipped_reread_lagging",
    "skipped_stale",
    "skipped_too_many_distinct_ids",
]

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
_REPAIR_PERSON_READ_SETTINGS = {"apply_deleted_mask": 0, "max_execution_time": 60, "max_memory_usage": 4_000_000_000}
_REPAIR_MAPPING_READ_SETTINGS = {"max_execution_time": 60, "max_memory_usage": 4_000_000_000}

# A scan reads only these fields, which keeps person properties out of the RPC payloads.
_VERSION_ONLY_READ_OPTIONS = ReadOptions(field_mask=["id", "uuid", "team_id", "version"])

_REPAIR_CHUNK_SIZE = 100
_MAPPING_QUERY_CHUNK_SIZE = 1_000
# A person with more distinct ids keeps its person repair, and its mappings are reported for a separate plan:
# one read of every mapping can exceed the gRPC message limit, and their paced writes would run for hours.
_MAX_REPAIR_DISTINCT_IDS_PER_PERSON = 1_000
_FLUSH_TIMEOUT_SECONDS = 5 * 60
# Confirmed produce results are dropped this often, so a long repair does not hold one per published row.
_DELIVERY_PRUNE_EVERY = 1_000

_T = TypeVar("_T")


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


@frozen
class PersonRef:
    team_id: int
    person_uuid: str

    def __post_init__(self) -> None:
        # Lookups key on the canonical form that ClickHouse toString(id) and the persons reads return.
        if str(UUID(self.person_uuid)) != self.person_uuid:
            raise ValueError(f"person_uuid must be a canonical lowercase UUID: {self.person_uuid!r}")


@frozen
class RepairAction:
    """One person row (``distinct_id`` is None) or one of its mappings, with what the repair did to it.

    A person with too many distinct ids to repair gets one extra row with no ``distinct_id`` and the
    outcome ``skipped_too_many_distinct_ids``, which stands for all of its mappings.
    """

    team_id: int
    person_uuid: str
    distinct_id: str | None
    kind: PersonDivergenceKind | MappingDivergenceKind | None
    pg_version: int | None
    ch_max_version: int | None
    target_version: int | None
    outcome: RepairOutcome


@frozen
class RepairSummary:
    applied: bool
    persons: int
    person_outcomes: dict[RepairOutcome, int]
    mapping_outcomes: dict[RepairOutcome, int]
    # Published rows that Kafka did not confirm: the delivery failed, or it was still queued at the deadline.
    undelivered: int


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


def _resolve_max_team_id(max_team_id: int | None) -> int:
    if max_team_id is not None:
        return max_team_id
    [[highest]] = _ch("SELECT max(team_id) FROM person", {}, _HIDDEN_SETTINGS)
    return int(highest or 0) + 1


def _chunks(items: Sequence[_T], size: int) -> list[Sequence[_T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


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


# ── Repair ───────────────────────────────────────────────────────────


@frozen
class _ChPersonState:
    visible_rows: int
    visible_max_version: int
    visible_winner_deleted: bool
    # Includes lightweight-deleted rows, so a republish lands above every row the sweep masked.
    max_version: int


@frozen
class _ChMappingState:
    max_version: int
    winner_deleted: bool
    winner_person_uuid: str


@frozen
class _MappingPlan:
    distinct_id: str
    kind: MappingDivergenceKind | None
    pg_version: int
    ch_max_version: int | None
    target_version: int


@frozen
class _PersonPlan:
    team_id: int
    person_uuid: str
    person: Person | None
    kind: PersonDivergenceKind | None
    ch_max_version: int | None
    target_version: int | None
    mappings: list[_MappingPlan]
    too_many_distinct_ids: bool = False


_PERSON_STATE_SQL = """
SELECT
    toString(id),
    countIf(_row_exists),
    maxIf(version, _row_exists),
    argMaxIf(is_deleted, version, _row_exists),
    max(version)
FROM person
WHERE team_id = %(team_id)s AND id IN %(person_uuids)s
GROUP BY id
"""

_MAPPING_STATE_SQL = """
SELECT distinct_id, max(version), argMax(is_deleted, version), toString(argMax(person_id, version))
FROM person_distinct_id2
WHERE team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s
GROUP BY distinct_id
"""


def _person_kind(pg_version: int, state: _ChPersonState | None) -> PersonDivergenceKind | None:
    # Any winner that differs from Postgres counts, whatever the versions: a raise whose publish
    # never landed leaves ClickHouse below Postgres, and a rerun must still finish it.
    if state is None:
        return "absent"
    if state.visible_rows == 0:
        return "swept"
    if state.visible_winner_deleted:
        return "hidden"
    if state.visible_max_version > pg_version:
        return "stale"
    if state.visible_max_version < pg_version:
        return "behind"
    return None


def _mapping_kind(person_uuid: str, pg_version: int, state: _ChMappingState | None) -> MappingDivergenceKind | None:
    if state is None:
        return "absent"
    if state.winner_deleted:
        return "hidden"
    if state.winner_person_uuid != person_uuid:
        return "other_person"
    # The owner matches, but a later move of this mapping would be written below the ClickHouse winner and lost.
    if state.max_version > pg_version:
        return "stale"
    return None


def _target_version(pg_version: int, ch_max_version: int | None) -> int:
    # One above ClickHouse, not 100 above: a later Postgres write or tombstone takes the next version
    # and must outrank this row.
    return pg_version if ch_max_version is None else max(pg_version, ch_max_version + 1)


def _ch_person_states(team_id: int, person_uuids: list[str]) -> dict[str, _ChPersonState]:
    rows = _ch(_PERSON_STATE_SQL, {"team_id": team_id, "person_uuids": person_uuids}, _REPAIR_PERSON_READ_SETTINGS)
    return {
        person_uuid: _ChPersonState(
            visible_rows=int(visible_rows),
            visible_max_version=int(visible_max_version),
            visible_winner_deleted=bool(visible_winner_deleted),
            max_version=int(max_version),
        )
        for person_uuid, visible_rows, visible_max_version, visible_winner_deleted, max_version in rows
    }


def _ch_mapping_states(team_id: int, distinct_ids: list[str]) -> dict[str, _ChMappingState]:
    states: dict[str, _ChMappingState] = {}
    for chunk in _chunks(distinct_ids, _MAPPING_QUERY_CHUNK_SIZE):
        rows = _ch(_MAPPING_STATE_SQL, {"team_id": team_id, "distinct_ids": list(chunk)}, _REPAIR_MAPPING_READ_SETTINGS)
        for distinct_id, max_version, winner_deleted, winner_person_uuid in rows:
            states[distinct_id] = _ChMappingState(
                max_version=int(max_version),
                winner_deleted=bool(winner_deleted),
                winner_person_uuid=winner_person_uuid,
            )
    return states


def _plan_chunk(team_id: int, person_uuids: Sequence[str]) -> list[_PersonPlan]:
    live = {str(p.uuid): p for p in get_persons_by_uuids(team_id, list(person_uuids), distinct_id_limit=0)}
    person_states = _ch_person_states(team_id, list(live)) if live else {}
    distinct_ids_by_person = (
        personhog_call(
            "person_divergence_repair_distinct_ids",
            lambda: _batched_get_distinct_ids_for_persons(
                team_id, [p.pk for p in live.values()], limit_per_person=_MAX_REPAIR_DISTINCT_IDS_PER_PERSON + 1
            ),
        )
        if live
        else {}
    )
    all_distinct_ids = [
        d.id
        for dids in distinct_ids_by_person.values()
        if len(dids) <= _MAX_REPAIR_DISTINCT_IDS_PER_PERSON
        for d in dids
    ]
    mapping_states = _ch_mapping_states(team_id, all_distinct_ids) if all_distinct_ids else {}

    plans: list[_PersonPlan] = []
    for person_uuid in person_uuids:
        person = live.get(person_uuid)
        if person is None:
            plans.append(
                _PersonPlan(
                    team_id=team_id,
                    person_uuid=person_uuid,
                    person=None,
                    kind=None,
                    ch_max_version=None,
                    target_version=None,
                    mappings=[],
                )
            )
            continue
        pg_version = int(person.version or 0)
        state = person_states.get(person_uuid)
        ch_max_version = state.max_version if state is not None else None
        person_distinct_ids = distinct_ids_by_person.get(person.pk, [])
        too_many_distinct_ids = len(person_distinct_ids) > _MAX_REPAIR_DISTINCT_IDS_PER_PERSON
        mappings = []
        for mapping in [] if too_many_distinct_ids else person_distinct_ids:
            mapping_state = mapping_states.get(mapping.id)
            mapping_ch_max = mapping_state.max_version if mapping_state is not None else None
            mappings.append(
                _MappingPlan(
                    distinct_id=mapping.id,
                    kind=_mapping_kind(person_uuid, mapping.version, mapping_state),
                    pg_version=mapping.version,
                    ch_max_version=mapping_ch_max,
                    target_version=_target_version(mapping.version, mapping_ch_max),
                )
            )
        plans.append(
            _PersonPlan(
                team_id=team_id,
                person_uuid=person_uuid,
                person=person,
                kind=_person_kind(pg_version, state),
                ch_max_version=ch_max_version,
                target_version=_target_version(pg_version, ch_max_version),
                mappings=mappings,
                too_many_distinct_ids=too_many_distinct_ids,
            )
        )
    return plans


def _raise_person_version_floor(team_id: int, person_id: int, min_version: int) -> None:
    personhog_call(
        "person_divergence_set_person_version_floor",
        lambda: require_personhog_client().set_person_version_floor(
            SetPersonVersionFloorRequest(team_id=team_id, person_id=person_id, min_version=min_version)
        ),
    )


def _raise_mapping_version_floor(team_id: int, distinct_id: str, min_version: int) -> str | None:
    """Raise the mapping's version on the primary and return the uuid of the person it maps to there."""
    response = personhog_call(
        "person_divergence_set_person_distinct_id_version_floor",
        lambda: require_personhog_client().set_person_distinct_id_version_floor(
            SetPersonDistinctIdVersionFloorRequest(team_id=team_id, distinct_id=distinct_id, min_version=min_version)
        ),
    )
    if not response.HasField("person"):
        return None
    return str(UUID(response.person.uuid))


def _primary_mapping_versions(team_id: int, person_id: int) -> dict[str, int]:
    response = personhog_call(
        "person_divergence_confirm_mapping_versions",
        lambda: require_personhog_client().get_distinct_ids_for_persons(
            GetDistinctIdsForPersonsRequest(
                team_id=team_id,
                person_ids=[person_id],
                read_options=ReadOptions(consistency=CONSISTENCY_LEVEL_STRONG),
                limit_per_person=_MAX_REPAIR_DISTINCT_IDS_PER_PERSON + 1,
            )
        ),
    )
    return {d.distinct_id: int(d.version or 0) for pd in response.person_distinct_ids for d in pd.distinct_ids}


def _person_action(plan: _PersonPlan, outcome: RepairOutcome) -> RepairAction:
    return RepairAction(
        team_id=plan.team_id,
        person_uuid=plan.person_uuid,
        distinct_id=None,
        kind=plan.kind,
        pg_version=int(plan.person.version or 0) if plan.person is not None else None,
        ch_max_version=plan.ch_max_version,
        target_version=plan.target_version if plan.kind is not None else None,
        outcome=outcome,
    )


def _too_many_distinct_ids_action(plan: _PersonPlan) -> RepairAction:
    return RepairAction(
        team_id=plan.team_id,
        person_uuid=plan.person_uuid,
        distinct_id=None,
        kind=None,
        pg_version=None,
        ch_max_version=None,
        target_version=None,
        outcome="skipped_too_many_distinct_ids",
    )


def _mapping_action(plan: _PersonPlan, mapping: _MappingPlan, outcome: RepairOutcome) -> RepairAction:
    return RepairAction(
        team_id=plan.team_id,
        person_uuid=plan.person_uuid,
        distinct_id=mapping.distinct_id,
        kind=mapping.kind,
        pg_version=mapping.pg_version,
        ch_max_version=mapping.ch_max_version,
        target_version=mapping.target_version if mapping.kind is not None else None,
        outcome=outcome,
    )


def _publish_person(team_id: int, person: Person) -> ProduceResult:
    row = _person_row(
        team_id=team_id,
        uuid=str(person.uuid),
        version=int(person.version or 0),
        properties=person.properties,
        is_identified=person.is_identified,
        is_deleted=False,
        created_at=person.created_at,
        last_seen_at=person.last_seen_at,
    )
    # _person_row fills a missing last_seen_at with the current hour, but ingestion publishes null for it.
    if person.last_seen_at is None:
        row["last_seen_at"] = None
    return ClickhouseProducer().produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=row)


def _execute_plan(
    plan: _PersonPlan,
    *,
    apply: bool,
    include_stale: bool,
    before_write: Callable[[], None],
    published: Callable[[ProduceResult], None],
) -> list[RepairAction]:
    person = plan.person
    if person is None:
        return [_person_action(plan, "skipped_not_live")]
    if plan.kind == "stale" and not include_stale:
        return [
            _person_action(plan, "skipped_stale"),
            *(
                _mapping_action(plan, m, "skipped_not_divergent" if m.kind is None else "skipped_stale")
                for m in plan.mappings
            ),
            *([_too_many_distinct_ids_action(plan)] if plan.too_many_distinct_ids else []),
        ]

    divergent_mappings = [m for m in plan.mappings if m.kind is not None]
    mapping_actions = [_mapping_action(plan, m, "skipped_not_divergent") for m in plan.mappings if m.kind is None]
    if plan.too_many_distinct_ids:
        mapping_actions.append(_too_many_distinct_ids_action(plan))
    if not apply:
        person_outcome: RepairOutcome = "would_repair" if plan.kind is not None else "skipped_not_divergent"
        return [
            _person_action(plan, person_outcome),
            *mapping_actions,
            *(_mapping_action(plan, m, "would_repair") for m in divergent_mappings),
        ]

    pg_version = int(person.version or 0)
    if plan.kind is not None and plan.target_version is not None and plan.target_version > pg_version:
        before_write()
        _raise_person_version_floor(plan.team_id, person.pk, plan.target_version)

    # SetPersonDistinctIdVersionFloor runs on the primary, so its reply is the owner check: the replica list
    # that produced this mapping can lag a merge that moved it to another person.
    owned: list[_MappingPlan] = []
    for mapping in divergent_mappings:
        before_write()
        owner = _raise_mapping_version_floor(plan.team_id, mapping.distinct_id, mapping.target_version)
        if owner is None:
            mapping_actions.append(_mapping_action(plan, mapping, "skipped_mapping_gone"))
        elif owner != plan.person_uuid:
            mapping_actions.append(_mapping_action(plan, mapping, "skipped_owner_changed"))
        else:
            owned.append(mapping)

    # Re-read after the raise so the published properties are the ones Postgres holds at the
    # published version, including any ingestion update that landed after the first read.
    reread: Person | None = None
    if plan.kind is not None:
        found = get_persons_by_uuids(plan.team_id, [plan.person_uuid], distinct_id_limit=0)
        reread = found[0] if found else None

    if (plan.kind is not None or owned) and _tombstoned_uuids(plan.team_id, [plan.person_uuid]):
        person_outcome = "skipped_tombstoned" if plan.kind is not None else "skipped_not_divergent"
        return [
            _person_action(plan, person_outcome),
            *mapping_actions,
            *(_mapping_action(plan, m, "skipped_tombstoned") for m in owned),
        ]

    if plan.kind is None:
        person_outcome = "skipped_not_divergent"
    elif reread is None:
        person_outcome = "skipped_not_live"
    elif plan.target_version is None or int(reread.version or 0) < plan.target_version:
        # The replica has not caught up with the raise, so its properties may predate the raised version.
        person_outcome = "skipped_reread_lagging"
    else:
        published(_publish_person(plan.team_id, reread))
        person_outcome = "repaired"

    # The SetPersonDistinctIdVersionFloor reply does not say whether it wrote, and a personhog-replica build
    # without NULL-version handling leaves a NULL version unchanged, so publish only the mappings whose
    # version on the primary reached the target.
    stored_versions = _primary_mapping_versions(plan.team_id, person.pk) if owned else {}
    for mapping in owned:
        stored_version = stored_versions.get(mapping.distinct_id)
        if stored_version is None:
            mapping_actions.append(_mapping_action(plan, mapping, "skipped_owner_changed"))
        elif stored_version < mapping.target_version:
            mapping_actions.append(_mapping_action(plan, mapping, "skipped_reread_lagging"))
        else:
            published(
                create_person_distinct_id(
                    team_id=plan.team_id,
                    distinct_id=mapping.distinct_id,
                    person_id=plan.person_uuid,
                    version=stored_version,
                    is_deleted=False,
                )
            )
            mapping_actions.append(_mapping_action(plan, mapping, "repaired"))
    return [_person_action(plan, person_outcome), *mapping_actions]


@frozen(frozen=False)
class _WritePacer:
    """Space writes at least 1 / max_per_second apart, so idle time never buys a later burst."""

    max_per_second: float | None
    next_write_at: float = 0.0

    def before_write(self) -> None:
        if self.max_per_second is None:
            return
        now = time.monotonic()
        if now < self.next_write_at:
            time.sleep(self.next_write_at - now)
            now = self.next_write_at
        self.next_write_at = now + 1 / self.max_per_second


@frozen(frozen=False)
class _Deliveries:
    """Kafka produce results of the published rows, so a failed delivery counts as undelivered."""

    pending: list[ProduceResult] = field(default_factory=list)
    failed: int = 0

    def track(self, result: ProduceResult) -> None:
        self.pending.append(result)
        if len(self.pending) >= _DELIVERY_PRUNE_EVERY:
            self._prune()

    def undelivered(self, timeout: float) -> int:
        flush_all_producers(timeout)
        self._prune()
        return self.failed + len(self.pending)

    def _prune(self) -> None:
        waiting: list[ProduceResult] = []
        for result in self.pending:
            if not result.done():
                waiting.append(result)
                continue
            try:
                result.get(timeout=0)
            except Exception:
                self.failed += 1
        self.pending = waiting


def repair_persons(
    targets: Sequence[PersonRef],
    *,
    apply: bool,
    include_stale: bool = False,
    max_writes_per_second: float | None = None,
    on_action: Callable[[RepairAction], None],
    log: Callable[[str], None],
) -> RepairSummary:
    """Republish the Postgres state of each target person and its mappings where ClickHouse disagrees.

    A rerun is safe: each Postgres write only raises a version, and a person whose publish never landed
    still counts as divergent. ``max_writes_per_second`` paces each Postgres write, one per divergent
    person or distinct id.

    ``include_stale`` also repairs stale persons and their mappings. That replaces their ClickHouse properties
    with the Postgres ones for good, so never use it on a team waiting for a restore from ClickHouse.
    """
    if max_writes_per_second is not None and max_writes_per_second <= 0:
        raise ValueError("max_writes_per_second must be above 0")
    by_team: dict[int, list[str]] = defaultdict(list)
    for target in dict.fromkeys(targets):
        by_team[target.team_id].append(target.person_uuid)

    person_outcomes: Counter[RepairOutcome] = Counter()
    mapping_outcomes: Counter[RepairOutcome] = Counter()
    processed = 0
    undelivered = 0
    pacer = _WritePacer(max_per_second=max_writes_per_second)
    deliveries = _Deliveries()
    existing_teams = set(Team.objects.filter(id__in=list(by_team)).values_list("id", flat=True))
    try:
        for team_id, person_uuids in sorted(by_team.items()):
            if team_id not in existing_teams:
                # A deleted team's ClickHouse rows go with the team, so a repair would only republish what the deletion removed.
                for person_uuid in person_uuids:
                    action = RepairAction(
                        team_id=team_id,
                        person_uuid=person_uuid,
                        kind=None,
                        pg_version=None,
                        ch_max_version=None,
                        target_version=None,
                        outcome="skipped_team_gone",
                    )
                    person_outcomes[action.outcome] += 1
                    on_action(action)
                    processed += 1
                log(f"team {team_id}: no longer exists, {len(person_uuids)} persons skipped")
                continue
            for chunk in _chunks(person_uuids, _REPAIR_CHUNK_SIZE):
                for plan in _plan_chunk(team_id, chunk):
                    for action in _execute_plan(
                        plan,
                        apply=apply,
                        include_stale=include_stale,
                        before_write=pacer.before_write,
                        published=deliveries.track,
                    ):
                        is_person_row = action.distinct_id is None and action.outcome != "skipped_too_many_distinct_ids"
                        (person_outcomes if is_person_row else mapping_outcomes)[action.outcome] += 1
                        on_action(action)
                    processed += 1
            log(f"team {team_id}: {len(person_uuids)} persons, {processed} processed in total")
    finally:
        if apply:
            undelivered = deliveries.undelivered(_FLUSH_TIMEOUT_SECONDS)
            if undelivered:
                log(f"{undelivered} ClickHouse messages were not delivered; rerun the repair for the same input")
    return RepairSummary(
        applied=apply,
        persons=processed,
        person_outcomes=dict(person_outcomes),
        mapping_outcomes=dict(mapping_outcomes),
        undelivered=undelivered,
    )
