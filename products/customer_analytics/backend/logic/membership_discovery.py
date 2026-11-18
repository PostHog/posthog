from collections.abc import Callable, Sequence
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

import structlog
from prometheus_client import Counter, Histogram

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.customer_analytics.backend.logic.membership import (
    MembershipCleanupBusy,
    MembershipExistence,
    MembershipKey,
    get_membership_cleanup_lease,
    get_membership_existence,
    get_membership_query_settings,
    renew_membership_cleanup_lease,
)
from products.customer_analytics.backend.logic.membership_metrics import (
    BATCH_DURATION_BUCKETS,
    SCAN_DURATION_BUCKETS,
    MembershipTimings,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)

if TYPE_CHECKING:
    from posthog.clickhouse.client.execute import ClickHouseExternalTable

logger = structlog.get_logger(__name__)
BATCH_SIZE = 100
TEAM_BATCH_SIZE = 25
DISCOVERY_LEASE_SECONDS = 15
OUTCOMES = Counter("customer_analytics_membership_discovery_total", "Membership discovery outcomes", ["outcome"])
SCAN_SECONDS = Histogram(
    "customer_analytics_membership_discovery_scan_seconds",
    "Membership full scan duration",
    buckets=SCAN_DURATION_BUCKETS,
)
BATCH_SECONDS = Histogram(
    "customer_analytics_membership_discovery_batch_seconds",
    "Membership discovery batch duration",
    buckets=BATCH_DURATION_BUCKETS,
)


@frozen
class MembershipDiscoveryInput:
    team_id: int

    def __post_init__(self) -> None:
        if self.team_id <= 0:
            raise ValueError("Membership discovery requires a positive team ID")


@frozen
class MembershipDiscoveryCounts:
    scanned: int = 0
    recovered: int = 0
    discovered: int = 0
    has_more: bool = False


def get_membership_key_table(keys: Sequence[MembershipKey]) -> "ClickHouseExternalTable":
    return {
        "name": "membership_keys",
        "structure": [("group_type_index", "UInt8"), ("group_key", "String"), ("distinct_id", "String")],
        "data": [
            {"group_type_index": key.group_type_index, "group_key": key.group_key, "distinct_id": key.distinct_id}
            for key in keys
        ],
    }


class MembershipDiscoveryStore:
    def __init__(self, deadline: float | None = None) -> None:
        self.deadline = deadline

    def list_teams(self, after: int) -> list[int]:
        rows = sync_execute(
            """SELECT DISTINCT team_id FROM distributed_person_group_membership_config
            WHERE team_id > %(after)s ORDER BY team_id LIMIT %(limit)s""",
            {"after": after, "limit": TEAM_BATCH_SIZE},
            settings=get_membership_query_settings(self.deadline),
            workload=Workload.OFFLINE,
        )
        teams = [row[0] for row in rows]
        cursor = after
        for _ in range(TEAM_BATCH_SIZE):
            rows = sync_execute(
                """SELECT team_id FROM person_group_membership
                WHERE team_id > %(after)s ORDER BY team_id LIMIT 1""",
                {"after": cursor},
                settings={
                    **get_membership_query_settings(self.deadline),
                    "max_execution_time": 2,
                    "optimize_read_in_order": "1",
                },
                workload=Workload.OFFLINE,
            )
            if not rows:
                break
            cursor = rows[0][0]
            teams.append(cursor)
        return sorted(set(teams))[:TEAM_BATCH_SIZE]

    def list_keys(self, team_id: int, cursor: list[int | str]) -> list[MembershipKey]:
        cursor_key = (
            MembershipKey(group_type_index=int(cursor[0]), group_key=str(cursor[1]), distinct_id=str(cursor[2]))
            if cursor
            else MembershipKey(group_type_index=0, group_key="", distinct_id="")
        )
        rows = sync_execute(
            """SELECT DISTINCT group_type_index, group_key, distinct_id FROM person_group_membership
            WHERE team_id = %(team_id)s
              AND (%(has_cursor)s = 0 OR (group_type_index, group_key, distinct_id) >=
                   (SELECT tuple(group_type_index, group_key, distinct_id) FROM membership_keys LIMIT 1))
            ORDER BY group_type_index, group_key, distinct_id LIMIT %(limit)s""",
            {
                "team_id": team_id,
                "has_cursor": bool(cursor),
                "limit": BATCH_SIZE + 1,
            },
            external_tables=[get_membership_key_table([cursor_key])],
            settings={**get_membership_query_settings(self.deadline), "optimize_distinct_in_order": "1"},
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        return [MembershipKey(group_type_index=row[0], group_key=row[1], distinct_id=row[2]) for row in rows]

    def get_existing_keys(self, team_id: int, keys: set[MembershipKey]) -> set[MembershipKey]:
        if not keys:
            return set()
        rows = sync_execute(
            """SELECT DISTINCT group_type_index, group_key, distinct_id FROM person_group_membership
            WHERE team_id = %(team_id)s
              AND (group_type_index, group_key, distinct_id) IN membership_keys""",
            {"team_id": team_id},
            external_tables=[get_membership_key_table(list(keys))],
            settings=get_membership_query_settings(self.deadline),
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        return {MembershipKey(group_type_index=row[0], group_key=row[1], distinct_id=row[2]) for row in rows}


def list_membership_discovery_teams(store: MembershipDiscoveryStore) -> list[int]:
    # Team zero holds the discovery cursor and never starts a project scan.
    scan, _ = MembershipCleanupScan.objects.for_team(0).get_or_create(team_id=0)
    with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.DATA_DELETION):
        stored = store.list_teams(scan.last_team_id)
    pending = list(
        MembershipCleanupScan.objects.unscoped()
        .filter(team_id__gt=scan.last_team_id)
        .order_by("team_id")
        .values_list("team_id", flat=True)[:TEAM_BATCH_SIZE]
    )
    teams = sorted(set(stored + pending))[:TEAM_BATCH_SIZE]
    if not teams:
        MembershipCleanupScan.objects.for_team(0).filter(last_team_id=scan.last_team_id).update(last_team_id=0)
    return teams


def record_membership_discovery_team(team_id: int) -> None:
    MembershipCleanupScan.objects.for_team(0).update(last_team_id=team_id)


def get_candidate_key(candidate: MembershipCleanupCandidate) -> MembershipKey:
    return MembershipKey(
        group_type_index=candidate.group_type_index, group_key=candidate.group_key, distinct_id=candidate.distinct_id
    )


def is_membership_missing(key: MembershipKey, side: str, existence: MembershipExistence, deleted_team: bool) -> bool:
    if deleted_team:
        return True
    if side == "person":
        return key.distinct_id not in existence.persons
    return (key.group_type_index, key.group_key) not in existence.groups


def _update_scan(scan: MembershipCleanupScan, next_key: MembershipKey | None, now: datetime) -> None:
    if scan.scan_started_at is None:
        scan.scan_started_at = now
    if next_key is None:
        scan.cursor = []
        SCAN_SECONDS.observe((now - scan.scan_started_at).total_seconds())
        scan.scan_started_at = None
    else:
        # The next unprocessed key keeps scan progress valid when membership rows disappear.
        scan.cursor = [next_key.group_type_index, next_key.group_key, next_key.distinct_id]
    scan.save(update_fields=["cursor", "scan_started_at"])


def _run_batch(
    input: MembershipDiscoveryInput,
    store: MembershipDiscoveryStore,
    scan: MembershipCleanupScan,
    check_lease: Callable[[], None],
    timings: MembershipTimings,
) -> MembershipDiscoveryCounts:
    candidates = MembershipCleanupCandidate.objects.for_team(input.team_id)
    with timings.measure("read_candidates"):
        pending = list(candidates.order_by("last_checked_at", "id")[:BATCH_SIZE])
    with timings.measure("scan_membership"):
        page = store.list_keys(input.team_id, scan.cursor)
    keys = page[:BATCH_SIZE]
    next_key = page[BATCH_SIZE] if len(page) > BATCH_SIZE else None
    pending_keys = {get_candidate_key(candidate) for candidate in pending}
    with timings.measure("check_membership"):
        all_keys = set(keys) | store.get_existing_keys(input.team_id, pending_keys - set(keys))
    with timings.measure("read_team"):
        deleted_team = not Team.objects.filter(id=input.team_id).exists()
    existence = (
        MembershipExistence(persons=frozenset(), groups=frozenset())
        if deleted_team
        else get_membership_existence(input.team_id, list(all_keys), deadline=store.deadline, timings=timings)
    )
    check_lease()
    now = timezone.now()
    with timings.measure("read_candidate_state"):
        existing = list(candidates.filter(key_hash__in=[key.get_hash() for key in all_keys | pending_keys]))
    erased_ids = [candidate.pk for candidate in existing if get_candidate_key(candidate) not in all_keys]
    recovered_ids = [
        candidate.pk
        for candidate in existing
        if get_candidate_key(candidate) in all_keys
        and not is_membership_missing(get_candidate_key(candidate), candidate.missing_side, existence, deleted_team)
    ]
    existing_sides = {(candidate.key_hash, candidate.missing_side) for candidate in existing}
    discovered = [
        MembershipCleanupCandidate(
            team_id=input.team_id,
            key_hash=key.get_hash(),
            group_type_index=key.group_type_index,
            group_key=key.group_key,
            distinct_id=key.distinct_id,
            missing_side=side,
            first_missing_at=now,
            last_checked_at=now,
        )
        for key in all_keys
        for side in ("person", "group")
        if (key.get_hash(), side) not in existing_sides and is_membership_missing(key, side, existence, deleted_team)
    ]
    check_lease()
    with timings.measure("write_checkpoint"), transaction.atomic():
        candidates.filter(pk__in=recovered_ids + erased_ids).delete()
        candidates.filter(pk__in=[candidate.pk for candidate in existing]).update(last_checked_at=now)
        candidates.bulk_create(discovered, ignore_conflicts=True)
        _update_scan(scan, next_key, now)
    for outcome, count in (
        ("scanned", len(keys)),
        ("recovered", len(recovered_ids)),
        ("erased", len(erased_ids)),
        ("discovered", len(discovered)),
    ):
        OUTCOMES.labels(outcome).inc(count)
    return MembershipDiscoveryCounts(
        scanned=len(keys), recovered=len(recovered_ids), discovered=len(discovered), has_more=next_key is not None
    )


def run_membership_discovery(
    input: MembershipDiscoveryInput, store: MembershipDiscoveryStore
) -> MembershipDiscoveryCounts:
    started = monotonic()
    timings = MembershipTimings(job="discovery")
    counts = MembershipDiscoveryCounts()
    outcome = "failure"
    acquired = False
    lease = get_membership_cleanup_lease(input.team_id, timeout=DISCOVERY_LEASE_SECONDS)

    try:
        with timings.measure("acquire_lease"):
            acquired = lease.acquire()
        if not acquired:
            outcome = "overlap"
            OUTCOMES.labels("overlap").inc()
            raise MembershipCleanupBusy("Membership cleanup is busy for this team. Retry the batch.")
        with timings.measure("read_scan_state"):
            scan, _ = MembershipCleanupScan.objects.for_team(input.team_id).get_or_create(team_id=input.team_id)
        with (
            renew_membership_cleanup_lease(lease, DISCOVERY_LEASE_SECONDS, store.deadline) as check_lease,
            tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.DATA_DELETION, team_id=input.team_id),
        ):
            counts = _run_batch(input, store, scan, check_lease, timings)
        outcome = "success"
        return counts
    finally:
        try:
            if acquired:
                with timings.measure("release_lease"):
                    if lease.owned():
                        lease.release()
        except BaseException:
            outcome = "failure"
            raise
        finally:
            elapsed = monotonic() - started
            BATCH_SECONDS.observe(elapsed)
            logger.info(
                "membership_discovery_batch",
                team_id=input.team_id,
                outcome=outcome,
                scanned=counts.scanned,
                recovered=counts.recovered,
                discovered=counts.discovered,
                has_more=counts.has_more,
                duration_seconds=elapsed,
                step_seconds=timings.seconds,
                failed_step=timings.failed_step,
            )
