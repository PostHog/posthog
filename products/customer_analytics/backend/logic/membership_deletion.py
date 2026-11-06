from collections.abc import Callable, Sequence
from datetime import timedelta
from functools import lru_cache
from time import monotonic

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from clickhouse_driver import Client
from prometheus_client import Counter, Histogram

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.deletion_targets import DeletionTarget, placement_for

from products.customer_analytics.backend.logic.membership import (
    MEMBERSHIP_LEASE_SECONDS,
    QUERY_SETTINGS,
    QUERY_TIMEOUT_SECONDS,
    MembershipExistence,
    MembershipKey,
    get_membership_cleanup_lease,
    get_membership_existence,
)
from products.customer_analytics.backend.logic.membership_discovery import get_candidate_key, is_membership_missing
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)

logger = structlog.get_logger(__name__)
BATCH_SIZE = 100
TEAM_BATCH_SIZE = 25
SOCKET_TIMEOUT_SECONDS = QUERY_TIMEOUT_SECONDS * 2
GRACE_PERIOD = timedelta(hours=24)
DELETION_COORDINATOR_TEAM_ID = -1
OUTCOMES = Counter("customer_analytics_membership_deletion_total", "Membership deletion outcomes", ["outcome"])
BATCH_SECONDS = Histogram("customer_analytics_membership_deletion_batch_seconds", "Membership deletion batch duration")


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
class MembershipDeletionInput:
    team_id: int
    dry_run: bool = True
    delete_team_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.team_id <= 0
            or len(self.delete_team_ids) > TEAM_BATCH_SIZE
            or any(team_id <= 0 for team_id in self.delete_team_ids)
        ):
            raise ValueError(
                "Membership deletion requires a positive team ID and at most 25 positive deletion team IDs"
            )


@frozen
class MembershipDeletionCounts:
    checked: int = 0
    recovered: int = 0
    overdue: int = 0
    deleted: int = 0
    has_more: bool = False


@lru_cache(maxsize=1)
def _get_cleanup_cluster(host: str) -> ClickhouseCluster:
    return get_cluster(
        host=host,
        connection_overrides={"send_receive_timeout": SOCKET_TIMEOUT_SECONDS},
        client_settings={
            **QUERY_SETTINGS,
            "log_comment": '{"product":"customer_analytics","workload":"OFFLINE","name":"membership-deletion"}',
        },
    )


class MembershipDeletionStore:
    def _delete(self, team_id: int, keys: Sequence[MembershipKey] | None = None) -> None:
        target = CONFIG_TARGET if keys is None else MEMBERSHIP_TARGET
        predicate = "team_id = %(team_id)s"
        parameters: dict[str, object] = {"team_id": team_id}
        if keys is not None:
            predicate += " AND (group_type_index, group_key, distinct_id) IN %(keys)s"
            parameters["keys"] = [(key.group_type_index, key.group_key, key.distinct_id) for key in keys]
        cluster = _get_cleanup_cluster(settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST or settings.CLICKHOUSE_HOST)
        placement = placement_for(cluster, target)
        if placement is None:
            return
        if not placement.cluster.shards:
            raise RuntimeError(
                "Membership deletion found no storage shards. Check the ClickHouse cluster configuration."
            )
        query_id = f"membership-deletion-{target.data_table}-{team_id}"

        # The cluster logs the callable representation, so keep membership keys in the closure.
        def delete_membership(client: Client) -> None:
            pending = client.execute(
                "SELECT count() FROM system.mutations WHERE database = currentDatabase() AND table = %(table)s AND NOT is_done",
                {"table": target.data_table},
                settings=QUERY_SETTINGS,
            )
            if pending[0][0]:
                raise RuntimeError("Membership deletion has a pending mutation. Retry the batch later.")
            remaining = client.execute(
                f"SELECT 1 FROM {escape_clickhouse_identifier(target.data_table)} WHERE {predicate} LIMIT 1",
                parameters,
                settings=QUERY_SETTINGS,
            )
            if not remaining:
                return
            client.execute(
                f"DELETE FROM {escape_clickhouse_identifier(target.data_table)} WHERE {predicate}",
                parameters,
                query_id=query_id,
                settings={**QUERY_SETTINGS, "lightweight_deletes_sync": "2", "replace_running_query": "0"},
            )

        placement.cluster.map_one_host_per_shard(delete_membership, concurrency=1).result()
        # nosemgrep: clickhouse-fstring-param-audit -- Only fixed SQL and escaped identifiers enter this string.
        survivors = sync_execute(
            f"SELECT count() FROM {escape_clickhouse_identifier(target.read_table)} WHERE {predicate}",
            parameters,
            settings=QUERY_SETTINGS,
            workload=Workload.OFFLINE,
        )
        if survivors[0][0]:
            raise RuntimeError("Membership deletion found surviving rows. Retry the batch later.")

    def delete_keys(self, team_id: int, keys: Sequence[MembershipKey]) -> None:
        self._delete(team_id, keys)

    def delete_config(self, team_id: int) -> None:
        self._delete(team_id)

    def has_membership(self, team_id: int) -> bool:
        return bool(
            sync_execute(
                "SELECT 1 FROM person_group_membership WHERE team_id = %(team_id)s LIMIT 1",
                {"team_id": team_id},
                settings=QUERY_SETTINGS,
                workload=Workload.OFFLINE,
            )
        )


def list_membership_deletion_teams() -> list[int]:
    # A separate coordinator row prevents deletion from advancing discovery's team cursor.
    scan, _ = MembershipCleanupScan.objects.for_team(DELETION_COORDINATOR_TEAM_ID).get_or_create(
        team_id=DELETION_COORDINATOR_TEAM_ID
    )
    pending = list(
        MembershipCleanupCandidate.objects.unscoped()
        .filter(team_id__gt=scan.last_team_id, first_missing_at__lte=timezone.now() - GRACE_PERIOD)
        .order_by("team_id")
        .values_list("team_id", flat=True)
        .distinct()[:TEAM_BATCH_SIZE]
    )
    deleted_teams = list(
        MembershipCleanupScan.objects.unscoped()
        .filter(team_id__gt=scan.last_team_id)
        .exclude(team_id__in=Team.objects.values("id"))
        .order_by("team_id")
        .values_list("team_id", flat=True)[:TEAM_BATCH_SIZE]
    )
    teams = sorted(set(pending + deleted_teams))[:TEAM_BATCH_SIZE]
    if not teams:
        MembershipCleanupScan.objects.for_team(DELETION_COORDINATOR_TEAM_ID).filter(
            last_team_id=scan.last_team_id
        ).update(last_team_id=0)
    return teams


def record_membership_deletion_team(team_id: int) -> None:
    MembershipCleanupScan.objects.for_team(DELETION_COORDINATOR_TEAM_ID).update(last_team_id=team_id)


def _delete_missing_membership(
    input: MembershipDeletionInput, store: MembershipDeletionStore, deleted_team: bool, keys: set[MembershipKey]
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
        logger.exception("membership_deletion_failed", team_id=input.team_id)
        return None


def _run_batch(
    input: MembershipDeletionInput, store: MembershipDeletionStore, check_lease: Callable[[], None]
) -> MembershipDeletionCounts:
    candidates = MembershipCleanupCandidate.objects.for_team(input.team_id)
    pending = list(
        candidates.filter(first_missing_at__lte=timezone.now() - GRACE_PERIOD).order_by("last_checked_at", "id")[
            :BATCH_SIZE
        ]
    )
    keys = {get_candidate_key(candidate) for candidate in pending}
    deleted_team = not Team.objects.filter(id=input.team_id).exists()
    existence = (
        MembershipExistence(persons=frozenset(), groups=frozenset())
        if deleted_team
        else get_membership_existence(input.team_id, list(keys))
    )
    check_lease()
    recovered_ids = [
        candidate.pk
        for candidate in pending
        if not is_membership_missing(get_candidate_key(candidate), candidate.missing_side, existence, deleted_team)
    ]
    deletable = {get_candidate_key(candidate) for candidate in pending if candidate.pk not in recovered_ids}
    scan = MembershipCleanupScan.objects.for_team(input.team_id).first()
    if scan is not None and scan.cursor:
        # Discovery must advance before deletion erases the key held in its saved cursor.
        deletable = {key for key in deletable if [key.group_type_index, key.group_key, key.distinct_id] != scan.cursor}
    with transaction.atomic():
        candidates.filter(pk__in=recovered_ids).delete()
        candidates.filter(pk__in=[candidate.pk for candidate in pending]).update(last_checked_at=timezone.now())
    check_lease()
    deletion_count = _delete_missing_membership(input, store, deleted_team, deletable)
    check_lease()
    deleted = deletion_count or 0
    if deleted:
        candidates.filter(key_hash__in=[key.get_hash() for key in deletable]).delete()
    if (
        deleted_team
        and deletion_count is not None
        and not candidates.exists()
        and not store.has_membership(input.team_id)
    ):
        MembershipCleanupScan.objects.for_team(input.team_id).delete()
    for outcome, count in (
        ("checked", len(pending)),
        ("recovered", len(recovered_ids)),
        ("overdue", len(deletable)),
        ("deleted", deleted),
    ):
        OUTCOMES.labels(outcome).inc(count)
    logger.info(
        "membership_deletion_batch",
        team_id=input.team_id,
        checked=len(pending),
        recovered=len(recovered_ids),
        overdue=len(deletable),
        deleted=deleted,
    )
    return MembershipDeletionCounts(
        checked=len(pending),
        recovered=len(recovered_ids),
        overdue=len(deletable),
        deleted=deleted,
        has_more=len(pending) == BATCH_SIZE and deleted + len(recovered_ids) > 0,
    )


def run_membership_deletion(input: MembershipDeletionInput, store: MembershipDeletionStore) -> MembershipDeletionCounts:
    started = monotonic()
    lease = get_membership_cleanup_lease(input.team_id)
    if not lease.acquire():
        OUTCOMES.labels("overlap").inc()
        return MembershipDeletionCounts()

    def check_lease() -> None:
        lease.extend(MEMBERSHIP_LEASE_SECONDS, replace_ttl=True)

    try:
        return _run_batch(input, store, check_lease)
    finally:
        if lease.owned():
            lease.release()
        BATCH_SECONDS.observe(monotonic() - started)
