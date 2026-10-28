from collections.abc import Sequence
from datetime import datetime, timedelta
from time import monotonic

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from prometheus_client import Counter, Histogram

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import Query, get_cluster
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.deletion_targets import DeletionTarget, placement_for

from products.customer_analytics.backend.logic.membership import (
    QUERY_SETTINGS,
    MembershipExistence,
    MembershipKey,
    get_membership_existence,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)

logger = structlog.get_logger(__name__)
BATCH_SIZE = 100
TEAM_BATCH_SIZE = 25
GRACE_PERIOD = timedelta(hours=24)
OUTCOMES = Counter("customer_analytics_membership_cleanup_total", "Membership cleanup outcomes", ["outcome"])
RECOVERY_SECONDS = Histogram(
    "customer_analytics_membership_recovery_seconds",
    "Missing membership recovery time",
    buckets=(60, 300, 900, 3600, 21600, 86400, 172800, 604800),
)
SCAN_SECONDS = Histogram(
    "customer_analytics_membership_scan_seconds",
    "Membership full scan duration",
    buckets=(1, 10, 60, 300, 3600, 21600, 86400, 604800),
)
BATCH_SECONDS = Histogram(
    "customer_analytics_membership_cleanup_batch_seconds",
    "Membership cleanup batch duration",
    buckets=(0.1, 1, 5, 15, 30, 60, 120, 300, 600),
)
CANDIDATE_AGE_SECONDS = Histogram(
    "customer_analytics_membership_candidate_age_seconds",
    "Observed overdue candidate age",
    buckets=(86400, 172800, 259200, 604800, 2592000, 7776000),
)

MEMBERSHIP_TARGET = DeletionTarget(
    data_table="sharded_person_group_membership",
    read_table="person_group_membership",
    cluster_setting="CLICKHOUSE_AUX_CLUSTER",
    node_role=NodeRole.AUX,
    optional=True,
)
CONFIG_TARGET = DeletionTarget(
    data_table="person_group_membership_config",
    read_table="distributed_person_group_membership_config",
    cluster_setting="CLICKHOUSE_AUX_CLUSTER",
    node_role=NodeRole.AUX,
    optional=True,
)


@frozen
class MembershipCleanupInput:
    team_id: int
    dry_run: bool = True
    delete_team_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.team_id <= 0 or len(self.delete_team_ids) > TEAM_BATCH_SIZE:
            raise ValueError("Membership cleanup requires a positive team ID and at most 25 deletion teams")


@frozen
class MembershipCleanupCounts:
    scanned: int = 0
    recovered: int = 0
    overdue: int = 0
    deleted: int = 0


class MembershipCleanupStore:
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
              AND (%(has_cursor)s = 0 OR (group_type_index, group_key, distinct_id) > %(cursor)s)
            ORDER BY group_type_index, group_key, distinct_id LIMIT %(limit)s""",
            {
                "team_id": team_id,
                "has_cursor": bool(cursor),
                "cursor": tuple(cursor or [0, "", ""]),
                "limit": BATCH_SIZE,
            },
            settings={**QUERY_SETTINGS, "optimize_distinct_in_order": "1"},
            workload=Workload.OFFLINE,
        )
        return [MembershipKey(group_type_index=row[0], group_key=row[1], distinct_id=row[2]) for row in rows]

    def _delete(self, team_id: int, keys: Sequence[MembershipKey] | None = None) -> None:
        target = CONFIG_TARGET if keys is None else MEMBERSHIP_TARGET
        predicate = "team_id = %(team_id)s"
        parameters: dict[str, object] = {"team_id": team_id}
        if keys is not None:
            predicate += " AND (group_type_index, group_key, distinct_id) IN %(keys)s"
            parameters["keys"] = [(key.group_type_index, key.group_key, key.distinct_id) for key in keys]
        cluster = get_cluster(
            host=settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST or settings.CLICKHOUSE_HOST,
            client_settings={
                **QUERY_SETTINGS,
                "log_comment": '{"product":"customer_analytics","workload":"OFFLINE","name":"membership-cleanup"}',
            },
        )
        placement = placement_for(cluster, target)
        if placement is None:
            return
        if not placement.cluster.shards:
            raise RuntimeError(
                "Membership cleanup found no storage shards. Check the ClickHouse cluster configuration."
            )
        capacity = placement.cluster.map_one_host_per_shard(
            Query(
                "SELECT count() FROM system.mutations WHERE database = currentDatabase() AND table = %(table)s AND NOT is_done",
                {"table": target.data_table},
                settings=QUERY_SETTINGS,
            ),
            concurrency=1,
        ).result()
        if any(rows[0][0] >= 5 for rows in capacity.values()):
            raise RuntimeError("Membership cleanup mutation capacity is full. Retry the batch later.")
        placement.cluster.map_one_host_per_shard(
            Query(
                f"ALTER TABLE {escape_clickhouse_identifier(target.data_table)} DELETE WHERE {predicate}",
                parameters,
                settings={**QUERY_SETTINGS, "mutations_sync": "2"},
            ),
            concurrency=1,
        ).result()
        # nosemgrep: clickhouse-fstring-param-audit -- Only fixed SQL and escaped identifiers enter this string.
        survivors = sync_execute(
            f"SELECT count() FROM {escape_clickhouse_identifier(target.read_table)} WHERE {predicate}",
            parameters,
            settings=QUERY_SETTINGS,
            workload=Workload.OFFLINE,
        )
        if survivors[0][0]:
            raise RuntimeError("Membership cleanup found surviving rows. Retry the batch later.")

    def delete_keys(self, team_id: int, keys: Sequence[MembershipKey]) -> None:
        self._delete(team_id, keys)

    def delete_config(self, team_id: int) -> None:
        self._delete(team_id)


def _list_team_page(store: MembershipCleanupStore, after: int) -> list[int]:
    stored = store.list_teams(after)
    pending = list(
        MembershipCleanupScan.objects.unscoped()
        .filter(team_id__gt=after)
        .order_by("team_id")
        .values_list("team_id", flat=True)[:TEAM_BATCH_SIZE]
    )
    return sorted(set(stored + pending))[:TEAM_BATCH_SIZE]


def list_membership_cleanup_teams(store: MembershipCleanupStore) -> list[int]:
    # Team zero holds the cross-project scan position. It never starts a project sweep.
    MembershipCleanupScan.objects.for_team(0).get_or_create(team_id=0)
    with transaction.atomic():
        scan = MembershipCleanupScan.objects.for_team(0).select_for_update().get()
        teams = _list_team_page(store, scan.last_team_id)
        if not teams and scan.last_team_id:
            teams = _list_team_page(store, 0)
        scan.last_team_id = teams[-1] if teams else 0
        scan.save(update_fields=["last_team_id"])
        return teams


def _get_key(candidate: MembershipCleanupCandidate) -> MembershipKey:
    return MembershipKey(
        group_type_index=candidate.group_type_index, group_key=candidate.group_key, distinct_id=candidate.distinct_id
    )


def _is_missing(key: MembershipKey, side: str, existence: MembershipExistence, deleted_team: bool) -> bool:
    if deleted_team:
        return True
    if side == "person":
        return key.distinct_id not in existence.persons
    return (key.group_type_index, key.group_key) not in existence.groups


def _delete_missing_membership(
    input: MembershipCleanupInput, store: MembershipCleanupStore, deleted_team: bool, keys: set[MembershipKey]
) -> int | None:
    if input.dry_run or input.team_id not in input.delete_team_ids:
        return None
    try:
        if deleted_team:
            store.delete_config(input.team_id)
        if keys:
            store.delete_keys(input.team_id, list(keys))
        return len(keys)
    except Exception:
        OUTCOMES.labels("deletion_failed").inc()
        logger.exception("membership_cleanup_deletion_failed", team_id=input.team_id)
        return None


def _update_scan(
    scan: MembershipCleanupScan, keys: list[MembershipKey], erased_keys: set[MembershipKey], now: datetime
) -> None:
    if scan.scan_started_at is None:
        scan.scan_started_at = now
    if len(keys) < BATCH_SIZE:
        scan.cursor = []
        SCAN_SECONDS.observe((now - scan.scan_started_at).total_seconds())
        scan.scan_started_at = None
    else:
        last = keys[-1]
        # Erased identifiers must not remain in the saved scan position.
        scan.cursor = [] if last in erased_keys else [last.group_type_index, last.group_key, last.distinct_id]
    scan.save(update_fields=["cursor", "scan_started_at"])


def _run_batch(
    input: MembershipCleanupInput, store: MembershipCleanupStore, scan: MembershipCleanupScan
) -> MembershipCleanupCounts:
    candidates = MembershipCleanupCandidate.objects.for_team(input.team_id)
    pending = list(candidates.order_by("last_checked_at", "id")[:BATCH_SIZE])
    keys = store.list_keys(input.team_id, scan.cursor)
    all_keys = list(set(keys + [_get_key(candidate) for candidate in pending]))
    deleted_team = not Team.objects.filter(id=input.team_id).exists()
    existence = get_membership_existence(input.team_id, all_keys)
    now = timezone.now()
    recovered = 0
    overdue = 0
    deletable: set[MembershipKey] = set()
    for candidate in pending:
        key = _get_key(candidate)
        if not _is_missing(key, candidate.missing_side, existence, deleted_team):
            RECOVERY_SECONDS.observe((now - candidate.first_missing_at).total_seconds())
            candidate.delete()
            recovered += 1
            continue
        candidate.last_checked_at = now
        candidate.save(update_fields=["last_checked_at"])
        if now - candidate.first_missing_at >= GRACE_PERIOD:
            overdue += 1
            CANDIDATE_AGE_SECONDS.observe((now - candidate.first_missing_at).total_seconds())
            deletable.add(key)
    for key in keys:
        for side in ("person", "group"):
            if _is_missing(key, side, existence, deleted_team):
                _, created = candidates.get_or_create(
                    team_id=input.team_id,
                    key_hash=key.get_hash(),
                    missing_side=side,
                    defaults={
                        "group_type_index": key.group_type_index,
                        "group_key": key.group_key,
                        "distinct_id": key.distinct_id,
                        "first_missing_at": now,
                        "last_checked_at": now,
                    },
                )
                if created:
                    OUTCOMES.labels("discovered").inc()
    deletion_count = _delete_missing_membership(input, store, deleted_team, deletable)
    deleted = deletion_count or 0
    if deleted:
        candidates.filter(key_hash__in=[key.get_hash() for key in deletable]).delete()
    if deleted_team and deletion_count is not None and not all_keys and not scan.cursor:
        scan.delete()
    else:
        _update_scan(scan, keys, deletable if deleted else set(), now)
    for outcome, count in (
        ("scanned", len(keys)),
        ("recovered", recovered),
        ("overdue", overdue),
        ("deleted", deleted),
    ):
        OUTCOMES.labels(outcome).inc(count)
    logger.info(
        "membership_cleanup_batch",
        team_id=input.team_id,
        scanned=len(keys),
        recovered=recovered,
        overdue=overdue,
        deleted=deleted,
    )
    return MembershipCleanupCounts(scanned=len(keys), recovered=recovered, overdue=overdue, deleted=deleted)


def run_membership_cleanup(input: MembershipCleanupInput, store: MembershipCleanupStore) -> MembershipCleanupCounts:
    started = monotonic()
    scans = MembershipCleanupScan.objects.for_team(input.team_id)
    scans.get_or_create(team_id=input.team_id)
    with transaction.atomic():
        # The row lock also excludes a timed-out activity whose database thread still runs.
        scan = scans.select_for_update(skip_locked=True).first()
        if scan is None:
            OUTCOMES.labels("overlap").inc()
            return MembershipCleanupCounts()
        result = _run_batch(input, store, scan)
    BATCH_SECONDS.observe(monotonic() - started)
    return result
