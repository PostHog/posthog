from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import partial
from hashlib import sha256

from django.conf import settings

from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException

from posthog.hogql.escape_sql import escape_clickhouse_identifier

from posthog.clickhouse.cluster import ClickhouseCluster, LightweightDeleteMutationRunner, NodeRole, Query
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.models.deletion_targets import (
    DeletionTarget,
    TargetPlacement,
    UnsweepableRowsError,
    UnsweptRowsError,
    resolve_placements,
)
from posthog.models.person_group_membership.sql import (
    DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
    PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX,
    PERSON_GROUP_MEMBERSHIP_TABLE,
    SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
)

MEMBERSHIP_DELETION_TARGETS = (
    DeletionTarget(
        data_table=SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE,
        read_table=PERSON_GROUP_MEMBERSHIP_TABLE,
        cluster_setting="CLICKHOUSE_AUX_CLUSTER",
        node_role=NodeRole.AUX,
        optional=True,
        stores_person_properties=False,
    ),
    DeletionTarget(
        data_table=PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
        read_table=DISTRIBUTED_PERSON_GROUP_MEMBERSHIP_CONFIG_TABLE,
        cluster_setting="CLICKHOUSE_AUX_CLUSTER",
        node_role=NodeRole.AUX,
        optional=True,
        stores_person_properties=False,
    ),
)
KEYS = "team_id, group_type_index, group_key, distinct_id"
KEY_COLUMNS = "team_id Int64, group_type_index UInt8, group_key String, distinct_id String, version UInt64 DEFAULT 0"
QUERY_SETTINGS = {
    "max_execution_time": "1800",
    "max_memory_usage": str(2 * 1024**3),
    "max_rows_in_set": "1000000",
    "max_bytes_in_set": str(256 * 1024**2),
    "set_overflow_mode": "throw",
    "distributed_foreground_insert": "1",
}
UNKNOWN_TABLE = 60


def _name(table: str) -> str:
    return escape_clickhouse_identifier(settings.CLICKHOUSE_DATABASE) + "." + escape_clickhouse_identifier(table)


def _exists(client: Client, table: str) -> bool:
    return bool(
        client.execute(
            "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(table)s",
            {"database": settings.CLICKHOUSE_DATABASE, "table": table},
        )[0][0]
    )


def _redact(parameters: Mapping[str, object] | None) -> dict[str, object]:
    return {key: "[REDACTED]" if key == "distinct_ids" else value for key, value in (parameters or {}).items()}


# ClickhouseCluster logs every task with %r, and distinct IDs can be email addresses.
# These reprs hide the bound distinct IDs. The executed statements still bind the real values.
class _RedactedDeleteRunner(LightweightDeleteMutationRunner):
    def __repr__(self) -> str:
        return LightweightDeleteMutationRunner.__repr__(replace(self, parameters=_redact(self.parameters)))


class _RedactedQuery(Query):
    def __repr__(self) -> str:
        return Query.__repr__(replace(self, parameters=_redact(self.parameters)))


# Staging tables belong to event deletion operations, which can drop them at any time. A create or drop
# that fails on some hosts leaves the storage on only part of the cluster, and its Distributed proxy then
# fails on the other shards. So staged keys are read and deleted on each host's storage table, and a host
# without that table holds no staged keys.
class _StagedQuery(_RedactedQuery):
    def __call__(self, client: Client) -> list[tuple]:
        try:
            return super().__call__(client)
        except ServerException as exc:
            if exc.code != UNKNOWN_TABLE:
                raise
            return []


def _on_staged_hosts(
    placement: TargetPlacement, sql: str, parameters: Mapping[str, object], **query_settings: str
) -> list[list[tuple]]:
    query = _StagedQuery(sql, dict(parameters), settings={**QUERY_SETTINGS, **query_settings})
    return list(placement.cluster.map_hosts_by_role(query, placement.cluster.shard_role).result().values())


def _delete(placement: TargetPlacement, predicate: str, parameters: Mapping[str, object]) -> None:
    runner = _RedactedDeleteRunner(
        table=placement.target.data_table,
        predicate=predicate,
        parameters=dict(parameters),
        settings={**QUERY_SETTINGS, "lightweight_deletes_sync": 2, "mutations_sync": 2},
        force=True,
        capacity_timeout=1800,
    )
    for host, waiter in placement.cluster.map_one_host_per_shard(runner).result().items():
        if host.shard_num is not None:
            placement.cluster.map_all_hosts_in_shard(host.shard_num, waiter.wait).result()


def _verify_empty(cluster: ClickhouseCluster, table: str, predicate: str, parameters: Mapping[str, object]) -> None:
    survivors = cluster.any_host_by_role(
        _RedactedQuery(
            f"SELECT count() FROM {_name(table)} WHERE {predicate}", dict(parameters), settings=QUERY_SETTINGS
        ),
        NodeRole.DATA,
    ).result()[0][0]
    if survivors:
        raise UnsweptRowsError(f"{table}: {survivors} membership rows remain after deletion")


def _delete_staged(placement: TargetPlacement, predicate: str, parameters: Mapping[str, object]) -> None:
    table = _name(placement.target.data_table)
    _on_staged_hosts(
        placement,
        f"DELETE FROM {table} WHERE {predicate}",
        parameters,
        lightweight_deletes_sync="2",
        mutations_sync="2",
    )
    counts = _on_staged_hosts(placement, f"SELECT count() FROM {table} WHERE {predicate}", parameters)
    if survivors := sum(rows[0][0] for rows in counts if rows):
        raise UnsweptRowsError(f"{placement.target.data_table}: {survivors} membership rows remain after deletion")


def _staged_placements(cluster: ClickhouseCluster) -> list[TargetPlacement]:
    handles = [cluster]
    if settings.CLICKHOUSE_AUX_CLUSTER != cluster.data_cluster_name:
        try:
            handles.append(cluster.sibling(settings.CLICKHOUSE_AUX_CLUSTER, NodeRole.AUX))
        except ServerException as exc:
            if exc.code != 701:
                raise
    placements: dict[str, TargetPlacement] = {}
    for handle in handles:
        tables = handle.map_hosts_by_role(
            Query(
                "SELECT name FROM system.tables WHERE database = %(db)s AND startsWith(name, 'membership_deletion_keys_')",
                {"db": settings.CLICKHOUSE_DATABASE},
            ),
            handle.shard_role,
        ).result()
        for rows in tables.values():
            for (table,) in rows:
                placements.setdefault(
                    table,
                    TargetPlacement(
                        target=DeletionTarget(
                            data_table=table, read_table=f"distributed_{table}", stores_person_properties=False
                        ),
                        cluster=handle,
                    ),
                )
    return list(placements.values())


def has_team_membership(cluster: ClickhouseCluster, team_id: int) -> bool:
    for placement in resolve_placements(cluster, MEMBERSHIP_DELETION_TARGETS[:1]):
        if cluster.any_host_by_role(
            Query(
                f"SELECT 1 FROM {_name(placement.target.read_table)} WHERE team_id = %(team_id)s LIMIT 1",
                {"team_id": team_id},
            ),
            NodeRole.DATA,
        ).result():
            return True
    return any(
        any(
            _on_staged_hosts(
                placement,
                f"SELECT 1 FROM {_name(placement.target.data_table)} WHERE team_id = %(team_id)s LIMIT 1",
                {"team_id": team_id},
            )
        )
        for placement in _staged_placements(cluster)
    )


def delete_distinct_ids(cluster: ClickhouseCluster, team_id: int, distinct_ids: Sequence[str]) -> None:
    if not distinct_ids:
        return
    placements = resolve_placements(cluster, MEMBERSHIP_DELETION_TARGETS[:1])
    staged = _staged_placements(cluster)
    for start in range(0, len(distinct_ids), 5000):
        predicate = "team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s"
        parameters = {"team_id": team_id, "distinct_ids": list(distinct_ids[start : start + 5000])}
        for placement in placements:
            _delete(placement, predicate, parameters)
            _verify_empty(cluster, placement.target.read_table, predicate, parameters)
        for placement in staged:
            _delete_staged(placement, predicate, parameters)


def delete_teams(cluster: ClickhouseCluster, team_ids: Sequence[int], *, include_config: bool = True) -> None:
    if not team_ids:
        return
    predicate = "team_id IN %(team_ids)s"
    parameters = {"team_ids": list(team_ids)}
    targets = MEMBERSHIP_DELETION_TARGETS if include_config else MEMBERSHIP_DELETION_TARGETS[:1]
    for placement in resolve_placements(cluster, targets):
        _delete(placement, predicate, parameters)
        _verify_empty(cluster, placement.target.read_table, predicate, parameters)
    for placement in _staged_placements(cluster):
        _delete_staged(placement, predicate, parameters)


def removes_account_group_property(cluster: ClickhouseCluster, team_id: int, properties: Sequence[str]) -> bool:
    # Rows for a previous account index stay after the team changes the index, so stored rows decide, not the config.
    indices = [i for i in range(PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX + 1) if f"$group_{i}" in properties]
    if not indices or not resolve_placements(cluster, MEMBERSHIP_DELETION_TARGETS[:1]):
        return False
    return bool(
        cluster.any_host_by_role(
            Query(
                f"SELECT 1 FROM {_name(PERSON_GROUP_MEMBERSHIP_TABLE)} "
                "WHERE team_id = %(team_id)s AND group_type_index IN %(indices)s LIMIT 1",
                {"team_id": team_id, "indices": indices},
            ),
            NodeRole.DATA,
        ).result()
    )


class MembershipReconciliation:
    def __init__(self, cluster: ClickhouseCluster, operation_id: str) -> None:
        self.cluster = cluster
        digest = sha256(operation_id.encode()).hexdigest()[:32]
        self.storage_table = f"membership_deletion_keys_{digest}"
        self.read_table = f"distributed_{self.storage_table}"

    def _placement(self) -> TargetPlacement | None:
        placements = resolve_placements(self.cluster, MEMBERSHIP_DELETION_TARGETS[:1])
        return placements[0] if placements else None

    def _create(self, placement: TargetPlacement) -> None:
        # reconcile reads storage through its proxy, so storage must never exist without its proxy.
        # Create the proxy first and drop it last.
        distributed = Distributed(
            self.storage_table, sharding_key="cityHash64(distinct_id)", cluster=placement.cluster.data_cluster_name
        )
        create_proxy = Query(
            f"CREATE TABLE IF NOT EXISTS {_name(self.read_table)} ({KEY_COLUMNS}) ENGINE = {distributed}"
        )
        self.cluster.map_hosts_by_role(create_proxy, NodeRole.DATA).result()
        placement.cluster.map_hosts_by_role(create_proxy, placement.cluster.shard_role).result()
        engine = ReplacingMergeTree(self.storage_table, ReplicationScheme.SHARDED, ver="version")
        # Retries must join the same replica set even when TEST assigns unique Keeper paths.
        engine.set_zookeeper_path_key(f"{settings.CLICKHOUSE_DATABASE}_{self.storage_table}")
        placement.cluster.map_hosts_by_role(
            Query(
                f"CREATE TABLE IF NOT EXISTS {_name(self.storage_table)} ({KEY_COLUMNS}) "
                f"ENGINE = {engine} ORDER BY ({KEYS})"
            ),
            placement.cluster.shard_role,
        ).result()

    @staticmethod
    def _event_keys(table: str, json_schema: bool, predicate: str) -> str:
        properties = "toJSONString(properties)" if json_schema else "properties"
        return (
            "SELECT team_id, toUInt8(group_index) AS group_type_index, "
            f"JSONExtractString({properties}, concat('$group_', toString(group_index))) AS group_key, "
            f"distinct_id, timestamp FROM {_name(table)} "
            f"ARRAY JOIN range({PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX + 1}) AS group_index "
            f"WHERE ({predicate}) AND group_key != ''"
        )

    def refuse_unswept_sources(self, sources: Sequence[tuple[str, bool, str, dict[str, object]]]) -> None:
        if (
            self._placement() is None
            or not self.cluster.any_host_by_role(
                Query(f"SELECT 1 FROM {_name(PERSON_GROUP_MEMBERSHIP_TABLE)} LIMIT 1"), NodeRole.DATA
            ).result()
        ):
            return
        for table, json_schema, predicate, parameters in sources:
            if not self.cluster.any_host_by_role(partial(_exists, table=table), NodeRole.DATA).result():
                continue
            candidates = self._event_keys(table, json_schema, predicate)
            count = self.cluster.any_host_by_role(
                Query(
                    f"SELECT count() FROM {_name(PERSON_GROUP_MEMBERSHIP_TABLE)} WHERE ({KEYS}) GLOBAL IN (SELECT DISTINCT {KEYS} FROM ({candidates}))",
                    parameters,
                    settings=QUERY_SETTINGS,
                ),
                NodeRole.DATA,
            ).result()[0][0]
            if count:
                raise UnsweepableRowsError(
                    f"{table} is skipped by this sweep but holds source events for {count} affected membership rows. Enable deletion of that source before retrying."
                )

    def stage(self, sources: Sequence[tuple[str, bool, str, dict[str, object]]]) -> None:
        placement = self._placement()
        if placement is None:
            return
        existing_stage = self.cluster.any_host_by_role(partial(_exists, table=self.read_table), NodeRole.DATA).result()
        if (
            not existing_stage
            and not self.cluster.any_host_by_role(
                Query(f"SELECT 1 FROM {_name(PERSON_GROUP_MEMBERSHIP_TABLE)} LIMIT 1"), NodeRole.DATA
            ).result()
        ):
            return
        self._create(placement)
        for table, json_schema, predicate, parameters in sources:
            candidates = self._event_keys(table, json_schema, predicate)
            self.cluster.any_host_by_role(
                Query(
                    f"INSERT INTO {_name(self.read_table)} ({KEYS}) SELECT DISTINCT {KEYS} FROM {_name(PERSON_GROUP_MEMBERSHIP_TABLE)} "
                    f"WHERE ({KEYS}) GLOBAL IN (SELECT DISTINCT {KEYS} FROM ({candidates}))",
                    parameters,
                    settings=QUERY_SETTINGS,
                ),
                NodeRole.DATA,
            ).result()
        placement.cluster.map_hosts_by_role(
            Query(f"SYSTEM SYNC REPLICA {_name(self.storage_table)}"), placement.cluster.shard_role
        ).result()

    def _survivors(self, sources: Sequence[tuple[str, bool]]) -> str:
        # Filtering by staged distinct IDs before the ARRAY JOIN skips the properties of every other user in the
        # team. It keeps the full history of each staged ID, so first_seen and last_seen stay correct.
        staged_ids = (
            f"(team_id, distinct_id) GLOBAL IN (SELECT DISTINCT team_id, distinct_id FROM {_name(self.read_table)})"
        )
        candidates = " UNION ALL ".join(
            self._event_keys(table, json_schema, staged_ids) for table, json_schema in sources
        )
        return (
            f"SELECT {KEYS}, min(timestamp) AS first_seen, max(timestamp) AS last_seen FROM ({candidates}) "
            f"WHERE ({KEYS}) GLOBAL IN (SELECT DISTINCT {KEYS} FROM {_name(self.read_table)}) GROUP BY {KEYS}"
        )

    def reconcile(self, sources: Sequence[tuple[str, bool]]) -> None:
        placement = self._placement()
        if (
            placement is None
            or not placement.cluster.any_host_by_role(
                partial(_exists, table=self.storage_table), placement.cluster.shard_role
            ).result()
        ):
            return
        if not sources:
            raise UnsweptRowsError("Membership reconciliation has no surviving event source")
        predicate = f"({KEYS}) GLOBAL IN (SELECT {KEYS} FROM {_name(self.read_table)})"
        _delete(placement, predicate, {})
        expected = self._survivors(sources)
        self.cluster.any_host_by_role(
            Query(
                f"INSERT INTO {_name(PERSON_GROUP_MEMBERSHIP_TABLE)} ({KEYS}, first_seen, last_seen) {expected}",
                settings=QUERY_SETTINGS,
            ),
            NodeRole.DATA,
        ).result()
        placement.cluster.map_hosts_by_role(
            Query(f"SYSTEM SYNC REPLICA {_name(SHARDED_PERSON_GROUP_MEMBERSHIP_TABLE)}"), placement.cluster.shard_role
        ).result()
        actual = (
            f"SELECT {KEYS}, min(first_seen) AS first_seen, max(last_seen) AS last_seen "
            f"FROM {_name(PERSON_GROUP_MEMBERSHIP_TABLE)} WHERE {predicate} GROUP BY {KEYS}"
        )
        mismatches = self.cluster.any_host_by_role(
            Query(
                "SELECT count() FROM ("
                f"SELECT {KEYS} FROM (SELECT *, 1 AS side FROM ({expected}) "
                f"UNION ALL SELECT *, -1 AS side FROM ({actual})) GROUP BY {KEYS} "
                "HAVING sum(side) != 0 OR min(first_seen) != max(first_seen) OR min(last_seen) != max(last_seen))",
                settings=QUERY_SETTINGS,
            ),
            NodeRole.DATA,
        ).result()[0][0]
        if mismatches:
            raise UnsweptRowsError(f"Membership reconciliation: {mismatches} associations differ from surviving events")

    def cleanup(self) -> None:
        placement = self._placement()
        if placement is None:
            return
        # Storage goes before its proxy, for the reason in _create.
        for table in (self.storage_table, self.read_table):
            query = Query(f"DROP TABLE IF EXISTS {_name(table)} SYNC")
            self.cluster.map_hosts_by_role(query, NodeRole.DATA).result()
            placement.cluster.map_hosts_by_role(query, placement.cluster.shard_role).result()
