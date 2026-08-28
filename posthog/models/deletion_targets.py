"""Which physical ClickHouse tables a data deletion has to sweep.

Erasing a person's data is not a property of the events table — it is a property of every table
that stores rows attributable to a person. This module is the one list of those tables, so a table
that starts carrying person data gets registered here rather than found by an auditor months later.

Every target is swept with predicates built only from columns all of them declare: ``team_id``,
``person_id``, ``distinct_id``, ``timestamp``, ``uuid``, ``event``.

The reasoning behind each registration, exclusion and known gap is in
docs/internal/clickhouse-deletion-coverage.md.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import partial

from django.conf import settings

from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE,
    EVENTS_DATA_TABLE,
    EVENTS_JSON_DATA_TABLE,
    SHARDED_EVENTS_RECENT_DATA_TABLE,
)
from posthog.models.flag_evaluations.sql import (
    FLAG_EVALUATIONS_DATA_TABLE,
    FLAG_EVALUATIONS_SOURCE_EVENT,
    FLAG_EVALUATIONS_TABLE,
)

COVERAGE_DOC = "docs/internal/clickhouse-deletion-coverage.md"

# ClickHouse's CLUSTER_DOESNT_EXIST, which clickhouse_driver does not name.
_CLUSTER_DOESNT_EXIST = 701


class DeletionCoverageError(Exception):
    """A deletion would report success while rows it named survive somewhere."""


class UnsweepableRowsError(DeletionCoverageError):
    """A deletion would report success while rows it cannot reach survive on another table."""


class UnreachableTargetError(DeletionCoverageError):
    """A registered target's storage table is on a cluster this handle cannot address."""


class UnsweptRowsError(DeletionCoverageError):
    """A sweep ran to completion and rows it was supposed to remove are still readable."""


class HogQLSchema(Enum):
    """Which schema a compiled HogQL predicate must target to run against a table."""

    LEGACY = "legacy"
    NATIVE_JSON = "native_json"


@dataclass(frozen=True, kw_only=True)
class DeletionTarget:
    """One physical table a deletion sweep runs against.

    ``data_table`` is the local per-shard storage table a mutation is issued on; ``read_table`` is
    the Distributed proxy a verification count reads through.

    The capability fields exist so a caller needing more than the schema-agnostic predicates fails
    loudly on a table that cannot take it, rather than skipping it silently.
    """

    data_table: str
    read_table: str
    # Name of the Django setting holding the cluster its storage table is on. A target naming a
    # cluster the job's handle does not address is swept through a sibling handle for that cluster.
    # Reachability is still decided by probing the hosts, not by comparing this against the handle's
    # cluster: two cluster names can cover the same nodes, which is what the dev stack and CI do.
    # Anything that may live elsewhere must also be ``optional``, since that is what makes the
    # storage table's presence a question rather than an assumption.
    cluster_setting: str = "CLICKHOUSE_CLUSTER"
    # Guarded on system.tables: the table sits behind a migration that may not have run everywhere.
    optional: bool = False
    # The schema a HogQL predicate compiles against here, None where no HogQL table definition
    # exists. A compiled fragment names physical columns (mat_*, the property-group maps, or JSON
    # subcolumns), so it only runs against the schema it was compiled for.
    hogql_schema: HogQLSchema | None = None
    # properties/person_properties can be rewritten in place. True needs both halves: the property
    # columns are DEFAULT-kind (assignable by ALTER UPDATE, as materialize() mints them), and the
    # property-rewrite machinery in posthog/dags/data_deletion_requests.py actually sweeps the
    # table, which today is hardcoded to the events tables. flag_evaluations satisfies only the
    # schema half, so flipping this without extending the sweep silently under-deletes.
    accepts_property_rewrite: bool = False
    # Read uuids from this table when queueing a deferred deletion. False where the rows duplicate
    # another target's uuids, which would queue each one twice.
    queue_uuid_candidates: bool = True
    # The event names this table can hold, None meaning unconstrained. Lets a request naming other
    # events skip this table without querying it.
    stored_events: frozenset[str] | None = None

    @property
    def cluster_name(self) -> str:
        return getattr(settings, self.cluster_setting)

    @property
    def accepts_hogql_predicate(self) -> bool:
        return self.hogql_schema is not None

    @property
    def uses_new_events_schema(self) -> bool:
        return self.hogql_schema is HogQLSchema.NATIVE_JSON

    def may_hold_any_of(self, events: Sequence[str]) -> bool:
        """Whether this table could hold rows for any of ``events``, empty meaning every event.

        A request naming only events a table never stores can skip it, which matters because
        counting to prove zero is not free: no target indexes ``event``, so the query reads the
        team's rows across whichever partitions the request's time range covers.
        """
        if not events or self.stored_events is None:
            return True
        return not self.stored_events.isdisjoint(events)


@dataclass(frozen=True, kw_only=True)
class TargetPlacement:
    """A target and the cluster handle whose shards carry its storage table.

    Sweeps dispatch per shard, and a handle enumerates the shards of exactly one cluster, so the
    two travel together: reading the target off one handle and dispatching it on another is the
    mistake this pairing exists to prevent.
    """

    target: DeletionTarget
    cluster: ClickhouseCluster


EVENTS = DeletionTarget(
    data_table=EVENTS_DATA_TABLE(),
    read_table="events",
    hogql_schema=HogQLSchema.LEGACY,
    accepts_property_rewrite=True,
)

EVENTS_JSON = DeletionTarget(
    data_table=EVENTS_JSON_DATA_TABLE,
    read_table=DISTRIBUTED_EVENTS_JSON_TABLE,
    optional=True,
    cluster_setting="CLICKHOUSE_EVENTS_CLUSTER",
    hogql_schema=HogQLSchema.NATIVE_JSON,
    accepts_property_rewrite=True,
    # Dual-written from the same events, so its uuids are the legacy table's.
    queue_uuid_candidates=False,
)

# Flag-evaluation telemetry carries the same person and group payload as events, so person, team
# and queued-uuid sweeps must reach it. It takes neither of the richer sweeps; both exclusions are
# explained in docs/internal/clickhouse-deletion-coverage.md. Its producer populates person_id
# exactly as the events pipeline does, so a person sweep matches on person_id like every other
# events-shaped table.
FLAG_EVALUATIONS = DeletionTarget(
    data_table=FLAG_EVALUATIONS_DATA_TABLE,
    read_table=FLAG_EVALUATIONS_TABLE,
    optional=True,
    stored_events=frozenset({FLAG_EVALUATIONS_SOURCE_EVENT}),
)

EVENTS_TARGETS: tuple[DeletionTarget, ...] = (EVENTS, EVENTS_JSON)
PERSONAL_DATA_TARGETS: tuple[DeletionTarget, ...] = (*EVENTS_TARGETS, FLAG_EVALUATIONS)

# Storage tables that carry person properties and are reclaimed by their TTL alone. Each entry is a
# decision that erasure may lag by the retention window, not an oversight.
#
# sharded_events_recent is a transient mirror of the last few days of events, on a 7-day TTL keyed
# on inserted_at. Seven days is a short enough window to accept as the erasure bound, and a sweep
# would race the TTL for little benefit.
TTL_ONLY_TABLES: frozenset[str] = frozenset({SHARDED_EVENTS_RECENT_DATA_TABLE()})


_TABLE_EXISTS_SQL = "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s"


def _table_exists_params(table: str) -> dict[str, str]:
    return {"database": settings.CLICKHOUSE_DATABASE, "name": table}


def _table_exists(client: Client, table: str) -> bool:
    [[count]] = client.execute(_TABLE_EXISTS_SQL, _table_exists_params(table))
    return bool(count)


def _table_exists_via_sync_execute(table: str) -> bool:
    result = sync_execute(_TABLE_EXISTS_SQL, _table_exists_params(table))
    return bool(result and result[0][0])


def _has_any_rows(client: Client, table: str) -> bool:
    # LIMIT 1 rather than count(): this only has to answer "is there anything here", and on a
    # multi-terabyte events table a count would read every part.
    # nosemgrep: clickhouse-fstring-param-audit (table is an internal constant, not user input)
    return bool(client.execute(f"SELECT 1 FROM {settings.CLICKHOUSE_DATABASE}.{table} LIMIT 1"))


def _assert_no_rows_behind_the_proxy(cluster: ClickhouseCluster, target: DeletionTarget) -> None:
    """Fail when a storage table no host here carries still has rows behind its Distributed proxy.

    A ``ClickhouseCluster`` addresses exactly one cluster: hosts come from ``system.clusters`` for
    that one name, and only hosts whose ``hostClusterRole`` macro is ``data`` carry a shard number,
    which is what every sharded mutation dispatches over. A Distributed table has no such limit and
    routes to whichever cluster its engine names, so it still reads rows this handle cannot touch.
    Skipping the target would complete the request while those rows survive.

    Silence when the proxy is missing or empty, which is the ordinary state of a table whose
    rollout has not reached this deployment.
    """

    def probe(client: Client) -> bool:
        if not _table_exists(client, target.read_table):
            return False
        return _has_any_rows(client, target.read_table)

    if not cluster.any_host_by_role(probe, NodeRole.DATA).result():
        return

    raise UnreachableTargetError(
        f"{target.data_table} is registered for deletion with its storage on cluster "
        f"{target.cluster_name!r}, and no data node of {cluster.data_cluster_name!r} carries it, "
        f"while its Distributed proxy {target.read_table} still returns rows. Sweeping without it "
        f"would report an erasure that did not happen. See {COVERAGE_DOC}."
    )


def _any_data_node_has(cluster: ClickhouseCluster, table: str) -> bool:
    """Whether any data node of ``cluster`` carries ``table``.

    ``any`` rather than ``all``: on a partially-migrated cluster the mutation fails loudly on the
    hosts missing the table, which is preferable to silently skipping a deletion.
    """
    results = cluster.map_hosts_by_role(partial(_table_exists, table=table), NodeRole.DATA).result()
    return any(results.values())


def _sibling_holding(cluster: ClickhouseCluster, target: DeletionTarget) -> ClickhouseCluster | None:
    """A handle for the target's own cluster, when that cluster is defined here and carries it."""
    if target.cluster_name == cluster.data_cluster_name:
        return None
    try:
        sibling = cluster.sibling(target.cluster_name)
    except ServerException as exc:
        if exc.code != _CLUSTER_DOESNT_EXIST:
            raise
        # No such cluster here, which is every deployment the split that moves this table has not
        # reached: local, CI, self-hosted. Leave the verdict to the proxy check.
        return None
    return sibling if _any_data_node_has(sibling, target.data_table) else None


def placement_for(cluster: ClickhouseCluster, target: DeletionTarget) -> TargetPlacement | None:
    """Where ``target`` can be swept from, refusing rather than skipping when nowhere can.

    Reachability is settled by probing hosts, never by comparing cluster names: two names can
    cover the same nodes, which is what the dev stack and CI do. So the handle in hand is tried
    first, and a sibling is built only for a table it does not carry.
    """
    if not target.optional or _any_data_node_has(cluster, target.data_table):
        return TargetPlacement(target=target, cluster=cluster)

    sibling = _sibling_holding(cluster, target)
    if sibling is not None:
        return TargetPlacement(target=target, cluster=sibling)

    _assert_no_rows_behind_the_proxy(cluster, target)
    return None


def dispatchable_here(cluster: ClickhouseCluster, target: DeletionTarget) -> bool:
    """Whether ``cluster``'s own shards carry ``target``, for sweeps bound to a single handle.

    Refuses instead of answering False when another cluster's shards carry it. A caller fanning
    out over ``cluster.shards`` cannot reach those rows, and skipping them would report work it
    never did.
    """
    placement = placement_for(cluster, target)
    if placement is None:
        return False
    if placement.cluster is cluster:
        return True
    raise UnreachableTargetError(
        f"{target.data_table} is stored on cluster {target.cluster_name!r}, which this sweep has no "
        f"way to reach: it dispatches per shard of {cluster.data_cluster_name!r}. Running without "
        f"it would report an erasure that did not happen. See {COVERAGE_DOC}."
    )


def resolve_placements(
    cluster: ClickhouseCluster, targets: Sequence[DeletionTarget] = PERSONAL_DATA_TARGETS
) -> list[TargetPlacement]:
    """Every target that can be swept, each paired with the handle that reaches it.

    Raises rather than narrowing when one that cannot be reached still holds rows; see
    ``placement_for``.
    """
    placements = (placement_for(cluster, target) for target in targets)
    return [placement for placement in placements if placement is not None]


def sweep_clusters(
    cluster: ClickhouseCluster, targets: Sequence[DeletionTarget] = PERSONAL_DATA_TARGETS
) -> list[ClickhouseCluster]:
    """Every distinct cluster a sweep over ``targets`` dispatches to, the handle in hand first.

    A mutation predicate that joins a dictionary needs that dictionary present on every cluster the
    mutation runs on, which is what this enumerates. The handle in hand is always included: sweeps
    over the replicated, non-sharded tables run there whatever the targets resolve to.
    """
    clusters = [cluster]
    for placement in resolve_placements(cluster, targets):
        if not any(placement.cluster is known for known in clusters):
            clusters.append(placement.cluster)
    return clusters


def resolve_targets_here(
    cluster: ClickhouseCluster, targets: Sequence[DeletionTarget] = PERSONAL_DATA_TARGETS
) -> list[DeletionTarget]:
    """The subset of ``targets`` ``cluster``'s own shards carry; see ``dispatchable_here``."""
    return [target for target in targets if dispatchable_here(cluster, target)]


def personal_data_tables(cluster: ClickhouseCluster) -> list[str]:
    """Every physical table a person, team, or queued-uuid deletion must sweep."""
    return [target.data_table for target in resolve_targets_here(cluster)]


def resolve_data_targets_via_sync_execute(targets: Sequence[DeletionTarget]) -> list[DeletionTarget]:
    """Targets whose storage table exists, for callers talking to ClickHouse via ``sync_execute``."""
    return [target for target in targets if not target.optional or _table_exists_via_sync_execute(target.data_table)]


def resolve_read_targets_via_sync_execute(
    targets: Sequence[DeletionTarget] = PERSONAL_DATA_TARGETS,
) -> list[DeletionTarget]:
    """Targets whose Distributed read table exists, for callers verifying a deletion completed."""
    return [target for target in targets if not target.optional or _table_exists_via_sync_execute(target.read_table)]


def surviving_rows_sql(read_table: str, predicate: str) -> str:
    """Count rows still matching ``predicate``, excluding ones a lightweight delete already hid.

    ``_row_exists = 1`` is what makes this a survivor count rather than a row count; without it
    every deleted row still reads as present until its parts merge.
    """
    # nosemgrep: clickhouse-fstring-param-audit (predicate built from internal helpers, not user input)
    return f"SELECT count() FROM {read_table} WHERE {predicate} AND _row_exists = 1"


def count_surviving_rows(cluster: ClickhouseCluster, target: DeletionTarget, predicate: str, params: dict) -> int:
    """Rows still matching ``predicate`` on ``target``, read through its Distributed proxy.

    Read on a data node, which is the only role these tables exist on. Bounded like the job's other
    scans: no target indexes ``event``, so this reads the team's rows across the request's
    partitions once the table is no longer empty.
    """
    query = Query(surviving_rows_sql(target.read_table, predicate), params, settings={"max_execution_time": "1800"})
    rows = cluster.any_host_by_role(query, NodeRole.DATA).result()
    return int(rows[0][0]) if rows else 0


def assert_no_unsweepable_rows(
    cluster: ClickhouseCluster,
    targets: Sequence[DeletionTarget],
    predicate: str,
    params: dict,
    *,
    events: Sequence[str],
    reason: str,
) -> None:
    """Fail when a target this request cannot sweep actually holds rows matching it.

    Pass targets already narrowed by ``resolve_targets``; this does not re-check presence.

    ``predicate`` must be the portable part of the criteria — no HogQL fragment, no
    materialized-column arms — so the count is a superset of what the deletion would have removed.
    ``events`` is the request's event filter, empty meaning every event.

    Deliberately gated on rows existing rather than on the request's shape: an unconditional
    refusal would block every request of that shape from the day it lands, including the ones with
    nothing to strand.
    """
    for target in targets:
        if not target.may_hold_any_of(events):
            continue

        count = count_surviving_rows(cluster, target, predicate, params)
        if count:
            raise UnsweepableRowsError(
                f"{count} row(s) in {target.read_table} match this request but cannot be deleted: {reason}"
            )


def assert_sweep_complete(
    cluster: ClickhouseCluster,
    targets: Sequence[DeletionTarget],
    predicate_for: Callable[[DeletionTarget], tuple[str, dict]],
    *,
    events: Sequence[str],
) -> None:
    """Fail when rows a finished sweep was supposed to have removed are still readable.

    Counts through the Distributed proxy rather than the storage tables the sweep mutated, so it
    also covers the rows those mutations never reached: a shard the handle does not enumerate, or a
    storage table on another cluster. Call it only once every mutation has been waited on, or it
    reports work still in flight.

    ``predicate_for`` returns the criteria to count per target, because a HogQL fragment compiles
    to different physical columns on the legacy and native-JSON schemas.
    """
    for target in targets:
        if not target.may_hold_any_of(events):
            continue

        predicate, params = predicate_for(target)
        count = count_surviving_rows(cluster, target, predicate, params)
        if count:
            raise UnsweptRowsError(
                f"the sweep finished but {count} row(s) it should have removed are still readable in "
                f"{target.read_table}. Completing now would report an erasure that did not happen. "
                f"See {COVERAGE_DOC}."
            )
