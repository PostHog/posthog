"""Executes repair plans: version raises, publishes, pacing, retries and delivery tracking."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import field
from functools import partial
from typing import TypeVar

import grpc

from posthog.dataclasses import frozen
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.topics import KAFKA_PERSON
from posthog.models.person import Person
from posthog.models.person.sql import INSERT_PERSON_SQL
from posthog.models.person.util import (
    _flush_person_producers,
    _person_row,
    create_person_distinct_id,
    get_person_by_distinct_id,
    get_persons_by_uuids,
)
from posthog.models.team import Team
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.interceptor import is_transient_rpc_error
from posthog.personhog_client.proto import (
    DISTINCT_ID_WRITE_ACTION_RAISE,
    DISTINCT_ID_WRITE_OUTCOME_PERSON_NOT_LIVE,
    DistinctIdWrite,
    DistinctIdWriteResult,
    PersonVersionFloor,
    RaisePersonVersionFloorsRequest,
    WriteDistinctIdsRequest,
    WriteDistinctIdsResponse,
)

from . import datatypes, lookups, repair_plan, stale_merge

_T = TypeVar("_T")


_REPAIR_CHUNK_SIZE = 100

# The most rows one personhog repair write takes.
_WRITE_BATCH_SIZE = 250

# The waits between re-reads give the replica about 0.5 s to show a raise, far above its usual lag of a few milliseconds.
_REREAD_BACKOFF_SECONDS = (0.025, 0.05, 0.1, 0.15, 0.175)

_TRANSIENT_RETRY_BACKOFF_SECONDS = (1.0, 2.0)

# FAILED_PRECONDITION is transient for the repair writes: personhog returns it only for a person whose lifecycle
# mark another operation holds, or for a row that changed between its read and its lock, and both clear on a retry.
_TRANSIENT_RPC_CODES = frozenset(
    {
        grpc.StatusCode.INTERNAL,
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.FAILED_PRECONDITION,
    }
)

_DB_TIMEOUT_METADATA_KEY = "x-db-timeout"

_FLUSH_TIMEOUT_SECONDS = 5 * 60

# Confirmed produce results are dropped this often, so a long repair does not hold one per published row.
_DELIVERY_PRUNE_EVERY = 1_000

_sleep = time.sleep


def _raise_person_version_floor(team_id: int, person_uuid: str, min_version: int) -> None:
    # Claims the person's lifecycle mark, so the raise waits out an in-flight merge or delete of the person.
    personhog_call(
        "person_divergence_raise_person_version_floors",
        lambda: require_personhog_client().raise_person_version_floors(
            RaisePersonVersionFloorsRequest(
                team_id=team_id, floors=[PersonVersionFloor(person_uuid=person_uuid, min_version=min_version)]
            )
        ),
    )


def _write_distinct_ids(request: WriteDistinctIdsRequest) -> WriteDistinctIdsResponse:
    return require_personhog_client().write_distinct_ids(request)


def _raise_mapping_version_floors(
    team_id: int, person_uuid: str, mappings: Sequence[repair_plan._MappingPlan], before_write: Callable[[], None]
) -> dict[str, DistinctIdWriteResult]:
    """Raise each live mapping of the person to its target version on the primary, in batches.

    A mapping that moved to another person, or was tombstoned, is left alone and reported with its current row.
    """
    results: dict[str, DistinctIdWriteResult] = {}
    for batch in lookups._chunks(list(mappings), _WRITE_BATCH_SIZE):
        before_write()
        request = WriteDistinctIdsRequest(
            team_id=team_id,
            writes=[
                DistinctIdWrite(
                    distinct_id=m.distinct_id,
                    action=DISTINCT_ID_WRITE_ACTION_RAISE,
                    person_uuid=person_uuid,
                    min_version=m.target_version,
                )
                for m in batch
            ],
        )
        response = personhog_call(
            "person_divergence_raise_mapping_versions",
            partial(_write_distinct_ids, request),
        )
        results.update({r.distinct_id: r for r in response.results})
    return results


def _person_action(plan: repair_plan._PersonPlan, outcome: datatypes.RepairOutcome) -> datatypes.RepairAction:
    return datatypes.RepairAction(
        team_id=plan.team_id,
        person_uuid=plan.person_uuid,
        distinct_id=None,
        kind=plan.kind,
        pg_version=int(plan.person.version or 0) if plan.person is not None else None,
        ch_max_version=plan.ch_max_version,
        target_version=plan.target_version if plan.kind is not None else None,
        outcome=outcome,
    )


def _too_many_distinct_ids_action(plan: repair_plan._PersonPlan) -> datatypes.RepairAction:
    return datatypes.RepairAction(
        team_id=plan.team_id,
        person_uuid=plan.person_uuid,
        distinct_id=None,
        kind=None,
        pg_version=None,
        ch_max_version=None,
        target_version=None,
        outcome="skipped_too_many_distinct_ids",
    )


def _mapping_action(
    plan: repair_plan._PersonPlan, mapping: repair_plan._MappingPlan, outcome: datatypes.RepairOutcome
) -> datatypes.RepairAction:
    return datatypes.RepairAction(
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


def _reread_person(team_id: int, person_uuid: str, target_version: int | None) -> Person | None:
    """Read the person from the replica again while it shows a version below ``target_version``."""
    found = get_persons_by_uuids(team_id, [person_uuid], distinct_id_limit=0)
    reread = found[0] if found else None
    for delay in _REREAD_BACKOFF_SECONDS:
        if reread is None or target_version is None or int(reread.version or 0) >= target_version:
            break
        _sleep(delay)
        found = get_persons_by_uuids(team_id, [person_uuid], distinct_id_limit=0)
        reread = found[0] if found else None
    return reread


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (*CH_TRANSIENT_ERRORS, ClickHouseQueryTimeOut)) or is_transient_rpc_error(
        exc, codes=_TRANSIENT_RPC_CODES
    )


def is_retryable(exc: BaseException) -> bool:
    """Whether a repair failed on a transient error that a later attempt can get past: a busy person, or
    personhog or ClickHouse briefly unavailable."""
    return _is_transient(exc)


def is_person_busy(exc: BaseException) -> bool:
    """Whether another operation, such as a merge or delete, held the person: its lifecycle mark was claimed, or
    a wait for its row lock timed out. Other transient errors mean a service was unavailable."""
    if is_transient_rpc_error(exc, codes=frozenset({grpc.StatusCode.FAILED_PRECONDITION})):
        return True
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, grpc.RpcError):
            code = getattr(current, "code", None)
            trailing = getattr(current, "trailing_metadata", None)
            if not callable(code) or code() != grpc.StatusCode.DEADLINE_EXCEEDED or not callable(trailing):
                return False
            # personhog-replica names the timeout that ended the call; only a lock wait means the person was busy.
            return any(key == _DB_TIMEOUT_METADATA_KEY and value == "lock_timeout" for key, value in trailing() or ())
        current = current.__cause__
    return False


def _retry_transient(fn: Callable[[], _T], *, what: str, log: Callable[[str], None]) -> _T:
    """Run ``fn`` again after a transient ClickHouse or personhog error, then re-raise once the retries run out.

    Repeating a step is safe because every repair write is idempotent: a version raise never lowers a
    version, and ClickHouse keeps one row per version.
    """
    for delay in _TRANSIENT_RETRY_BACKOFF_SECONDS:
        try:
            return fn()
        except Exception as exc:
            if not _is_transient(exc):
                raise
            log(f"{what}: {type(exc).__name__}, retrying in {delay:g} s")
        _sleep(delay)
    return fn()


def _execute_plan(
    plan: repair_plan._PersonPlan,
    *,
    apply: bool,
    include_stale: bool,
    before_write: Callable[[], None],
    published: Callable[[ProduceResult], None],
    stale_merge_distinct_id: str | None = None,
) -> list[datatypes.RepairAction]:
    person = plan.person
    if person is None:
        return [_person_action(plan, "skipped_not_live")]
    if plan.kind == "stale" and not include_stale:
        refusal: datatypes.RepairOutcome | None = "skipped_stale"
        if apply and stale_merge_distinct_id is not None:
            missing = stale_merge._clickhouse_only_properties(plan)
            # A later reset that finds nothing missing raises Postgres. Capture accepting the $set does not mean
            # ingestion applies it, and a raise without the merged properties lets the next update overwrite them.
            refusal = (
                (stale_merge._queue_stale_merge(plan, stale_merge_distinct_id, missing) or "merge_queued")
                if missing
                else None
            )
        if refusal is not None:
            return [
                _person_action(plan, refusal),
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
        person_outcome: datatypes.RepairOutcome = "would_repair" if plan.kind is not None else "skipped_not_divergent"
        return [
            _person_action(plan, person_outcome),
            *mapping_actions,
            *(_mapping_action(plan, m, "would_repair") for m in divergent_mappings),
        ]

    pg_version = int(person.version or 0)
    if plan.kind is not None and plan.target_version is not None and plan.target_version > pg_version:
        before_write()
        _raise_person_version_floor(plan.team_id, plan.person_uuid, plan.target_version)

    # The raise runs on the primary, so its reply is the owner check: the replica list that produced this
    # mapping can lag a merge that moved it to another person.
    written = (
        _raise_mapping_version_floors(plan.team_id, plan.person_uuid, divergent_mappings, before_write)
        if divergent_mappings
        else {}
    )
    owned: list[repair_plan._MappingPlan] = []
    stored_versions: dict[str, int] = {}
    for mapping in divergent_mappings:
        result = written.get(mapping.distinct_id)
        row = result.row if result is not None and result.HasField("row") else None
        if result is not None and result.outcome == DISTINCT_ID_WRITE_OUTCOME_PERSON_NOT_LIVE:
            mapping_actions.append(_mapping_action(plan, mapping, "skipped_tombstoned"))
        elif row is None or row.is_deleted:
            mapping_actions.append(_mapping_action(plan, mapping, "skipped_mapping_gone"))
        elif row.person_uuid != plan.person_uuid:
            mapping_actions.append(_mapping_action(plan, mapping, "skipped_owner_changed"))
        else:
            owned.append(mapping)
            stored_versions[mapping.distinct_id] = int(row.version)

    # Re-read after the raise so the published properties are the ones Postgres holds at the
    # published version, including any ingestion update that landed after the first read.
    reread: Person | None = None
    if plan.kind is not None:
        reread = _reread_person(plan.team_id, plan.person_uuid, plan.target_version)

    if (plan.kind is not None or owned) and lookups._tombstoned_uuids(plan.team_id, [plan.person_uuid]):
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

    # The write reply holds the row the primary stored, at or above the target, so it is the version to publish.
    for mapping in owned:
        published(
            create_person_distinct_id(
                team_id=plan.team_id,
                distinct_id=mapping.distinct_id,
                person_id=plan.person_uuid,
                version=stored_versions[mapping.distinct_id],
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
        _flush_person_producers(timeout)
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


@frozen(frozen=False)
class _OutcomeCounts:
    person: Counter[datatypes.RepairOutcome] = field(default_factory=Counter)
    mapping: Counter[datatypes.RepairOutcome] = field(default_factory=Counter)

    def add(self, action: datatypes.RepairAction) -> None:
        is_person_row = action.distinct_id is None and action.outcome != "skipped_too_many_distinct_ids"
        (self.person if is_person_row else self.mapping)[action.outcome] += 1

    def summary(self, *, applied: bool, persons: int, undelivered: int) -> datatypes.RepairSummary:
        return datatypes.RepairSummary(
            applied=applied,
            persons=persons,
            person_outcomes=dict(self.person),
            mapping_outcomes=dict(self.mapping),
            undelivered=undelivered,
        )


def repair_persons(
    targets: Sequence[datatypes.PersonRef],
    *,
    apply: bool,
    include_stale: bool = False,
    max_writes_per_second: float | None = None,
    on_action: Callable[[datatypes.RepairAction], None],
    log: Callable[[str], None],
) -> datatypes.RepairSummary:
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

    outcomes = _OutcomeCounts()
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
                    action = datatypes.RepairAction(
                        team_id=team_id,
                        person_uuid=person_uuid,
                        distinct_id=None,
                        kind=None,
                        pg_version=None,
                        ch_max_version=None,
                        target_version=None,
                        outcome="skipped_team_gone",
                    )
                    outcomes.add(action)
                    on_action(action)
                    processed += 1
                log(f"team {team_id}: no longer exists, {len(person_uuids)} persons skipped")
                continue
            for chunk in lookups._chunks(person_uuids, _REPAIR_CHUNK_SIZE):
                plans = _retry_transient(
                    partial(repair_plan._plan_chunk, team_id, chunk), what=f"team {team_id}: planning", log=log
                )
                for plan in plans:
                    # Only the attempt that succeeds returns actions, so a retried person is counted once.
                    actions = _retry_transient(
                        partial(
                            _execute_plan,
                            plan,
                            apply=apply,
                            include_stale=include_stale,
                            before_write=pacer.before_write,
                            published=deliveries.track,
                        ),
                        what=f"team {team_id} person {plan.person_uuid}",
                        log=log,
                    )
                    for action in actions:
                        outcomes.add(action)
                        on_action(action)
                    processed += 1
            log(f"team {team_id}: {len(person_uuids)} persons, {processed} processed in total")
    finally:
        if apply:
            undelivered = deliveries.undelivered(_FLUSH_TIMEOUT_SECONDS)
            if undelivered:
                log(f"{undelivered} ClickHouse messages were not delivered; rerun the repair for the same input")
    return outcomes.summary(applied=apply, persons=processed, undelivered=undelivered)


def repair_distinct_id(
    team_id: int, distinct_id: str, *, delivery_timeout_seconds: float
) -> datatypes.RepairSummary | None:
    """Repair the live person that owns ``distinct_id``, and that one mapping, where ClickHouse disagrees.

    It always applies. For a stale person whose ClickHouse winner holds properties Postgres lacks, it sends them
    to ingestion as $set_once, so newer Postgres values win, and writes nothing else. A later reset, once
    ingestion applied them, raises Postgres above ClickHouse and republishes. It leaves the person stale when the
    team has property access rules.
    """
    owner = get_person_by_distinct_id(team_id, distinct_id, distinct_id_limit=0)
    if owner is None:
        return None
    outcomes = _OutcomeCounts()
    deliveries = _Deliveries()
    undelivered = 0
    try:
        for plan in repair_plan._plan_chunk(team_id, [str(owner.uuid)], only_distinct_id=distinct_id):
            for action in _execute_plan(
                plan,
                apply=True,
                include_stale=False,
                before_write=lambda: None,
                published=deliveries.track,
                stale_merge_distinct_id=distinct_id,
            ):
                outcomes.add(action)
    finally:
        undelivered = deliveries.undelivered(delivery_timeout_seconds)
    return outcomes.summary(applied=True, persons=1, undelivered=undelivered)
