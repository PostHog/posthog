from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from time import monotonic

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

import structlog
from clickhouse_driver import Client
from prometheus_client import Counter, Histogram

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.execute import default_settings, kill_switch_overrides
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.deletion_targets import DeletionTarget, placement_for
from posthog.settings import CLICKHOUSE_PER_TEAM_QUERY_SETTINGS

from products.customer_analytics.backend.logic.membership import (
    MAX_GROUP_KEY_LENGTH,
    MEMBERSHIP_LEASE_SECONDS,
    QUERY_TIMEOUT_SECONDS,
    MembershipCleanupBusy,
    MembershipExistence,
    MembershipKey,
    get_membership_cleanup_lease,
    get_membership_existence,
    get_membership_query_settings,
)
from products.customer_analytics.backend.logic.membership_discovery import get_candidate_key, is_membership_missing
from products.customer_analytics.backend.logic.membership_metrics import BATCH_DURATION_BUCKETS, MembershipTimings
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
BATCH_SECONDS = Histogram(
    "customer_analytics_membership_deletion_batch_seconds",
    "Membership deletion batch duration",
    buckets=BATCH_DURATION_BUCKETS,
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
    failed_batches: int = 0
    has_more: bool = False


def _get_deletion_query_settings(team_id: int, deadline: float | None) -> dict[str, str | int | float]:
    team_settings = CLICKHOUSE_PER_TEAM_QUERY_SETTINGS.get(str(team_id), {})
    query_settings: dict[str, str | int | float] = {
        **default_settings(),
        **team_settings,
        **get_membership_query_settings(deadline),
    }
    ceilings = kill_switch_overrides(team_id)
    for name in ceilings.keys() | {"max_execution_time"}:
        limits = [float(query_settings[name])] if name in query_settings else []
        if name in team_settings:
            limits.append(float(team_settings[name]))
        if name in ceilings:
            limits.append(ceilings[name])
        positive_limits = [limit for limit in limits if limit > 0]
        if positive_limits:
            limit = float(min(positive_limits))
            query_settings[name] = int(limit) if limit.is_integer() else limit
    return query_settings


def _get_deletion_predicate(team_id: int, keys: Sequence[MembershipKey] | None) -> tuple[str, dict[str, object]]:
    predicate = "team_id = %(team_id)s"
    parameters: dict[str, object] = {"team_id": team_id}
    if keys is None:
        return predicate, parameters
    predicate += " AND group_type_index IN %(group_types)s"
    parameters["group_types"] = sorted({key.group_type_index for key in keys})
    for column in ("group_key", "distinct_id"):
        values = {getattr(key, column) for key in keys}
        short_values = sorted(value for value in values if len(value) <= MAX_GROUP_KEY_LENGTH)
        prefixes = sorted({value[:MAX_GROUP_KEY_LENGTH] for value in values if len(value) > MAX_GROUP_KEY_LENGTH})
        filters = []
        if short_values:
            parameters[column] = short_values
            filters.append(f"{column} IN %({column})s")
        for index, prefix in enumerate(prefixes):
            parameter = f"{column}_prefix_{index}"
            parameters[parameter] = prefix
            filters.append(f"startsWith({column}, %({parameter})s)")
        predicate += " AND (" + " OR ".join(filters or ["0"]) + ")"
    # Prefixes bound SQL size while digests prevent deleting a prefix collision.
    predicate += " AND (group_type_index, hex(SHA256(group_key)), hex(SHA256(distinct_id))) IN %(key_hashes)s"
    parameters["key_hashes"] = [
        (
            key.group_type_index,
            sha256(key.group_key.encode()).hexdigest().upper(),
            sha256(key.distinct_id.encode()).hexdigest().upper(),
        )
        for key in keys
    ]
    return predicate, parameters


def _get_cleanup_cluster(host: str, team_id: int, deadline: float | None = None) -> ClickhouseCluster:
    query_settings = _get_deletion_query_settings(team_id, deadline)
    return get_cluster(
        host=host,
        connection_overrides={"send_receive_timeout": SOCKET_TIMEOUT_SECONDS},
        discovery_deadline=deadline,
        client_settings={
            **{name: str(value) for name, value in query_settings.items()},
            "log_comment": '{"product":"customer_analytics","workload":"OFFLINE","name":"membership-deletion"}',
        },
    )


class MembershipDeletionStore:
    def __init__(self, deadline: float | None = None) -> None:
        self.deadline = deadline
        self.timings = MembershipTimings(job="deletion")

    @contextmanager
    def _query(self, team_id: int, stage: str) -> Iterator[None]:
        with self.timings.measure(stage):
            try:
                yield
            except Exception as error:
                code = getattr(error, "code", None)
                logger.warning(
                    "membership_deletion_query_failed",
                    team_id=team_id,
                    stage=stage,
                    error_code=code if isinstance(code, int) else None,
                )
                # Driver errors can contain membership keys after parameter substitution.
                raise RuntimeError(f"Membership deletion query failed at {stage}. Retry the batch.") from None

    def _delete(self, team_id: int, keys: Sequence[MembershipKey] | None = None) -> None:
        target = CONFIG_TARGET if keys is None else MEMBERSHIP_TARGET
        predicate, parameters = _get_deletion_predicate(team_id, keys)
        with self.timings.measure("resolve_storage"):
            cluster = _get_cleanup_cluster(
                settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST or settings.CLICKHOUSE_HOST, team_id, self.deadline
            )
            placement = placement_for(cluster, target)
            if placement is not None and not placement.cluster.shards:
                raise RuntimeError(
                    "Membership deletion found no storage shards. Check the ClickHouse cluster configuration."
                )
        if placement is None:
            return
        query_id = f"membership-deletion-{target.data_table}-{team_id}"

        # The cluster logs the callable representation, so keep membership keys in the closure.
        def delete_membership(client: Client) -> None:
            with self._query(team_id, "check_pending_mutations"):
                pending = client.execute(
                    "SELECT count() FROM system.mutations WHERE database = currentDatabase() AND table = %(table)s AND NOT is_done",
                    {"table": target.data_table},
                    settings=_get_deletion_query_settings(team_id, self.deadline),
                )
                if pending[0][0]:
                    raise RuntimeError("Membership deletion has a pending mutation. Retry the batch later.")
            with self._query(team_id, "read_erasure_targets"):
                remaining = client.execute(
                    f"SELECT 1 FROM {escape_clickhouse_identifier(target.data_table)} WHERE {predicate} LIMIT 1",
                    parameters,
                    settings=_get_deletion_query_settings(team_id, self.deadline),
                )
            if not remaining:
                return
            with self._query(team_id, "delete_config" if keys is None else "delete_membership"):
                client.execute(
                    f"DELETE FROM {escape_clickhouse_identifier(target.data_table)} WHERE {predicate}",
                    parameters,
                    query_id=query_id,
                    settings={
                        **_get_deletion_query_settings(team_id, self.deadline),
                        "lightweight_deletes_sync": "2",
                        "replace_running_query": "0",
                    },
                )

        placement.cluster.map_one_host_per_shard(delete_membership, concurrency=1).result()
        with self._query(team_id, "verify_config_erasure" if keys is None else "verify_membership_erasure"):
            # nosemgrep: clickhouse-fstring-param-audit -- Only fixed SQL and escaped identifiers enter this string.
            survivors = sync_execute(
                f"SELECT count() FROM {escape_clickhouse_identifier(target.read_table)} WHERE {predicate}",
                parameters,
                settings=_get_deletion_query_settings(team_id, self.deadline),
                team_id=team_id,
                workload=Workload.OFFLINE,
                send_receive_timeout=SOCKET_TIMEOUT_SECONDS,
            )
            if survivors[0][0]:
                raise RuntimeError("Membership deletion found surviving rows. Retry the batch later.")

    def delete_keys(self, team_id: int, keys: Sequence[MembershipKey]) -> None:
        self._delete(team_id, keys)

    def delete_config(self, team_id: int) -> None:
        self._delete(team_id)

    def has_membership(self, team_id: int) -> bool:
        with self._query(team_id, "verify_team_empty"):
            return bool(
                sync_execute(
                    "SELECT 1 FROM person_group_membership WHERE team_id = %(team_id)s LIMIT 1",
                    {"team_id": team_id},
                    settings=_get_deletion_query_settings(team_id, self.deadline),
                    team_id=team_id,
                    workload=Workload.OFFLINE,
                    send_receive_timeout=SOCKET_TIMEOUT_SECONDS,
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
        .filter(~Exists(Team.objects.filter(id=OuterRef("team_id"))))
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
    except TimeoutError:
        raise
    except Exception:
        OUTCOMES.labels("deletion_failed").inc()
        store.timings.failed_step = store.timings.failed_step or "erase_membership"
        logger.warning("membership_deletion_failed", team_id=input.team_id, stage=store.timings.failed_step)
        return None


def _run_batch(
    input: MembershipDeletionInput, store: MembershipDeletionStore, check_lease: Callable[[], None]
) -> MembershipDeletionCounts:
    candidates = MembershipCleanupCandidate.objects.for_team(input.team_id)
    with store.timings.measure("read_candidates"):
        pending = list(
            candidates.filter(first_missing_at__lte=timezone.now() - GRACE_PERIOD).order_by("last_checked_at", "id")[
                :BATCH_SIZE
            ]
        )
    keys = {get_candidate_key(candidate) for candidate in pending}
    with store.timings.measure("read_team"):
        deleted_team = not Team.objects.filter(id=input.team_id).exists()
    existence = (
        MembershipExistence(persons=frozenset(), groups=frozenset())
        if deleted_team
        else get_membership_existence(input.team_id, list(keys), deadline=store.deadline, timings=store.timings)
    )
    check_lease()
    recovered_ids = [
        candidate.pk
        for candidate in pending
        if not is_membership_missing(get_candidate_key(candidate), candidate.missing_side, existence, deleted_team)
    ]
    deletable = {get_candidate_key(candidate) for candidate in pending if candidate.pk not in recovered_ids}
    with store.timings.measure("read_scan_state"):
        scan = MembershipCleanupScan.objects.for_team(input.team_id).first()
    if scan is not None and scan.cursor:
        # Discovery must advance before deletion erases the key held in its saved cursor.
        deletable = {key for key in deletable if [key.group_type_index, key.group_key, key.distinct_id] != scan.cursor}
    with store.timings.measure("write_checkpoint"), transaction.atomic():
        candidates.filter(pk__in=recovered_ids).delete()
        candidates.filter(pk__in=[candidate.pk for candidate in pending]).update(last_checked_at=timezone.now())
    check_lease()
    deletion_count = _delete_missing_membership(input, store, deleted_team, deletable)
    check_lease()
    deleted = deletion_count or 0
    if deleted:
        with store.timings.measure("clear_candidates"):
            candidates.filter(key_hash__in=[key.get_hash() for key in deletable]).delete()
    if (
        deleted_team
        and deletion_count is not None
        and not candidates.exists()
        and not store.has_membership(input.team_id)
    ):
        check_lease()
        with store.timings.measure("clear_scan_state"):
            MembershipCleanupScan.objects.for_team(input.team_id).delete()
    for outcome, count in (
        ("checked", len(pending)),
        ("recovered", len(recovered_ids)),
        ("overdue", len(deletable)),
        ("deleted", deleted),
    ):
        OUTCOMES.labels(outcome).inc(count)
    return MembershipDeletionCounts(
        checked=len(pending),
        recovered=len(recovered_ids),
        overdue=len(deletable),
        deleted=deleted,
        failed_batches=int(store.timings.failed_step is not None),
        has_more=len(pending) == BATCH_SIZE and deleted + len(recovered_ids) > 0,
    )


def run_membership_deletion(input: MembershipDeletionInput, store: MembershipDeletionStore) -> MembershipDeletionCounts:
    started = monotonic()
    store.timings = MembershipTimings(job="deletion")
    counts = MembershipDeletionCounts()
    outcome = "failure"
    acquired = False
    lease = get_membership_cleanup_lease(input.team_id)

    def check_lease() -> None:
        get_membership_query_settings(store.deadline)
        lease.extend(MEMBERSHIP_LEASE_SECONDS, replace_ttl=True)

    try:
        with store.timings.measure("acquire_lease"):
            acquired = lease.acquire()
        if not acquired:
            outcome = "overlap"
            OUTCOMES.labels("overlap").inc()
            raise MembershipCleanupBusy("Membership cleanup is busy for this team. Retry the batch.")
        counts = _run_batch(input, store, check_lease)
        outcome = "failure" if counts.failed_batches else "success"
        return counts
    finally:
        try:
            if acquired:
                with store.timings.measure("release_lease"):
                    if lease.owned():
                        lease.release()
        except BaseException:
            outcome = "failure"
            raise
        finally:
            elapsed = monotonic() - started
            BATCH_SECONDS.observe(elapsed)
            logger.info(
                "membership_deletion_batch",
                team_id=input.team_id,
                outcome=outcome,
                checked=counts.checked,
                recovered=counts.recovered,
                overdue=counts.overdue,
                deleted=counts.deleted,
                failed_batches=counts.failed_batches,
                has_more=counts.has_more,
                dry_run=input.dry_run,
                deletion_enabled=not input.dry_run and input.team_id in input.delete_team_ids,
                skip_reason="dry_run"
                if input.dry_run
                else "not_allowlisted"
                if input.team_id not in input.delete_team_ids
                else None,
                duration_seconds=elapsed,
                step_seconds=store.timings.seconds,
                failed_step=store.timings.failed_step,
            )
