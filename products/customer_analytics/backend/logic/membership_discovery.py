from collections.abc import Callable
from datetime import datetime
from time import monotonic

from django.db import transaction
from django.utils import timezone

import structlog
from prometheus_client import Counter, Histogram

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.customer_analytics.backend.logic.membership import (
    MEMBERSHIP_LEASE_SECONDS,
    QUERY_SETTINGS,
    MembershipExistence,
    MembershipKey,
    get_membership_cleanup_lease,
    get_membership_existence,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)

logger = structlog.get_logger(__name__)
BATCH_SIZE = 100
TEAM_BATCH_SIZE = 25
OUTCOMES = Counter("customer_analytics_membership_discovery_total", "Membership discovery outcomes", ["outcome"])
SCAN_SECONDS = Histogram("customer_analytics_membership_discovery_scan_seconds", "Membership full scan duration")
BATCH_SECONDS = Histogram(
    "customer_analytics_membership_discovery_batch_seconds", "Membership discovery batch duration"
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


class MembershipDiscoveryStore:
    def list_teams(self, after: int) -> list[int]:
        rows = sync_execute(
            """SELECT DISTINCT team_id FROM distributed_person_group_membership_config
            WHERE team_id > %(after)s ORDER BY team_id LIMIT %(limit)s""",
            {"after": after, "limit": TEAM_BATCH_SIZE},
            settings=QUERY_SETTINGS,
            workload=Workload.OFFLINE,
        )
        teams = [row[0] for row in rows]
        cursor = after
        for _ in range(TEAM_BATCH_SIZE):
            rows = sync_execute(
                """SELECT team_id FROM person_group_membership
                WHERE team_id > %(after)s ORDER BY team_id LIMIT 1""",
                {"after": cursor},
                settings={**QUERY_SETTINGS, "max_execution_time": "2", "optimize_read_in_order": "1"},
                workload=Workload.OFFLINE,
            )
            if not rows:
                break
            cursor = rows[0][0]
            teams.append(cursor)
        return sorted(set(teams))[:TEAM_BATCH_SIZE]

    def list_keys(self, team_id: int, cursor: list[int | str]) -> list[MembershipKey]:
        rows = sync_execute(
            """SELECT DISTINCT group_type_index, group_key, distinct_id FROM person_group_membership
            WHERE team_id = %(team_id)s
              AND (%(has_cursor)s = 0 OR (group_type_index, group_key, distinct_id) >= %(cursor)s)
            ORDER BY group_type_index, group_key, distinct_id LIMIT %(limit)s""",
            {
                "team_id": team_id,
                "has_cursor": bool(cursor),
                "cursor": tuple(cursor or [0, "", ""]),
                "limit": BATCH_SIZE + 1,
            },
            settings={**QUERY_SETTINGS, "optimize_distinct_in_order": "1"},
            workload=Workload.OFFLINE,
        )
        return [MembershipKey(group_type_index=row[0], group_key=row[1], distinct_id=row[2]) for row in rows]


def list_membership_discovery_teams(store: MembershipDiscoveryStore) -> list[int]:
    # Team zero holds the discovery cursor and never starts a project scan.
    scan, _ = MembershipCleanupScan.objects.for_team(0).get_or_create(team_id=0)
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
) -> MembershipDiscoveryCounts:
    candidates = MembershipCleanupCandidate.objects.for_team(input.team_id)
    pending = list(candidates.order_by("last_checked_at", "id")[:BATCH_SIZE])
    page = store.list_keys(input.team_id, scan.cursor)
    keys = page[:BATCH_SIZE]
    next_key = page[BATCH_SIZE] if len(page) > BATCH_SIZE else None
    all_keys = set(keys + [get_candidate_key(candidate) for candidate in pending])
    deleted_team = not Team.objects.filter(id=input.team_id).exists()
    existence = (
        MembershipExistence(persons=frozenset(), groups=frozenset())
        if deleted_team
        else get_membership_existence(input.team_id, list(all_keys))
    )
    check_lease()
    now = timezone.now()
    existing = list(candidates.filter(key_hash__in=[key.get_hash() for key in all_keys]))
    recovered_ids = [
        candidate.pk
        for candidate in existing
        if not is_membership_missing(get_candidate_key(candidate), candidate.missing_side, existence, deleted_team)
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
    with transaction.atomic():
        candidates.filter(pk__in=recovered_ids).delete()
        candidates.filter(pk__in=[candidate.pk for candidate in existing]).update(last_checked_at=now)
        candidates.bulk_create(discovered, ignore_conflicts=True)
        _update_scan(scan, next_key, now)
    for outcome, count in (("scanned", len(keys)), ("recovered", len(recovered_ids)), ("discovered", len(discovered))):
        OUTCOMES.labels(outcome).inc(count)
    logger.info(
        "membership_discovery_batch",
        team_id=input.team_id,
        scanned=len(keys),
        recovered=len(recovered_ids),
        discovered=len(discovered),
    )
    return MembershipDiscoveryCounts(
        scanned=len(keys), recovered=len(recovered_ids), discovered=len(discovered), has_more=next_key is not None
    )


def run_membership_discovery(
    input: MembershipDiscoveryInput, store: MembershipDiscoveryStore
) -> MembershipDiscoveryCounts:
    started = monotonic()
    lease = get_membership_cleanup_lease(input.team_id)
    if not lease.acquire():
        OUTCOMES.labels("overlap").inc()
        return MembershipDiscoveryCounts()

    def check_lease() -> None:
        lease.extend(MEMBERSHIP_LEASE_SECONDS, replace_ttl=True)

    try:
        scan, _ = MembershipCleanupScan.objects.for_team(input.team_id).get_or_create(team_id=input.team_id)
        return _run_batch(input, store, scan, check_lease)
    finally:
        if lease.owned():
            lease.release()
        BATCH_SECONDS.observe(monotonic() - started)
