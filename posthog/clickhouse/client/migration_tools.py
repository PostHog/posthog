import re
import logging
from dataclasses import dataclass
from functools import cache
from typing import Any, Optional

from infi.clickhouse_orm import migrations

from posthog import settings
from posthog.clickhouse.client.connection import DATA_NODE_ROLES, SINGLE_SHARD_DATA_NODE_ROLES, ClickHouseUser, NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, Query, get_cluster
from posthog.run_mode import run_mode
from posthog.settings.data_stores import (
    CLICKHOUSE_CLUSTER,
    CLICKHOUSE_MIGRATIONS_CLUSTER,
    CLICKHOUSE_MIGRATIONS_HOST,
    CLICKHOUSE_SATELLITE_CLUSTERS,
)

logger = logging.getLogger("migrations")


@cache
def get_migrations_cluster() -> ClickhouseCluster:
    return get_cluster(
        host=CLICKHOUSE_MIGRATIONS_HOST,
        cluster=CLICKHOUSE_MIGRATIONS_CLUSTER,
        data_cluster=CLICKHOUSE_CLUSTER,
        satellite_clusters=CLICKHOUSE_SATELLITE_CLUSTERS or None,
        ch_user=ClickHouseUser.MIGRATIONS,
    )


_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class _QueryIfTableExists:
    query: Query
    table: str

    def __call__(self, client) -> Any:
        if not client.execute(f"EXISTS TABLE {self.table}")[0][0]:
            logger.info("       Skipping, table %s does not exist on this host", self.table)
            return None
        return self.query(client)


def collapses_to_all_nodes() -> bool:
    return (settings.E2E_TESTING or not run_mode().is_deployed_cloud) and not settings.MULTINODE_CLICKHOUSE


def run_sql_with_exceptions(
    sql: str,
    node_roles: list[NodeRole] | NodeRole | None = None,
    sharded: Optional[bool] = None,
    is_alter_on_replicated_table: Optional[bool] = None,
    require_hosts: bool = False,
    only_if_table_exists: str | None = None,
):
    """
    Executes a SQL query on each node separately with specific options, handling distributed execution and node roles.

    This function executes a given SQL statement with the ability to target specific
    roles and node configurations. It supports distributed query execution for sharded
    or non-sharded deployments and takes into account cluster configurations. Additionally,
    it accommodates operations such as those on replicated tables.

    Parameters:
    sql: str
        The SQL query to be executed.
    node_roles: List of roles to execute the migration on, optional (default is NodeRole.DATA if not specified)
        Specifies which type of node the query should target during execution.
        In general, run everything on NodeRole.DATA except changes to sharded tables / writable distributed tables.
    sharded: bool, optional (default is False)
        Indicates if the migration is on a sharded table
    is_alter_on_replicated_table: bool, optional (default is False)
        Specifies whether the query is an ALTER statement executed on replicated tables.
        This will run on just one host per shard or one host for the whole cluster if there is no sharding.
    require_hosts: bool, optional (default is False)
        Raises when none of the requested node roles exist in the migration topology.
    only_if_table_exists: str, optional
        Runs the query only on hosts where this table exists in the default database. Use it for
        objects that only some installs have, such as tables from an earlier generation of a schema.

    Returns:
    migrations.RunPython
        A high-level representation capable of running the migration query in the specified
        context, including its distribution across nodes based on input parameters.

    Raises:
    AssertionError
        Raised in certain scenarios when the input arguments conflict with the expected
        configuration, such as when the sharded flag is set for roles other than DATA.
    """

    if only_if_table_exists is not None and not _TABLE_NAME.match(only_if_table_exists):
        raise ValueError(f"only_if_table_exists must be a plain table name, got {only_if_table_exists!r}")

    if node_roles and not isinstance(node_roles, list):
        node_roles = [node_roles]

    node_roles_list: list[NodeRole] = node_roles if isinstance(node_roles, list) else [NodeRole.DATA]

    # Store original node_roles for validation purposes before debug override
    original_node_roles = node_roles_list

    if collapses_to_all_nodes():
        # In E2E tests, debug mode and hobby deployments, we run migrations on ALL nodes
        # because we don't have different ClickHouse topologies yet in Docker.
        # MULTINODE_CLICKHOUSE opts back into role-based routing so the smoke-test
        # stack can verify migrations actually land on the correct cluster.
        node_roles_list = [NodeRole.ALL]

    def run_migration():
        cluster = get_migrations_cluster()

        query: Query | _QueryIfTableExists = (
            Query(sql) if only_if_table_exists is None else _QueryIfTableExists(Query(sql), only_if_table_exists)
        )

        if sharded and is_alter_on_replicated_table:
            is_local_or_test = collapses_to_all_nodes()
            single_role = node_roles_list[0] if len(node_roles_list) == 1 else None
            assert is_local_or_test or (single_role is not None and single_role in DATA_NODE_ROLES), (
                "When running migrations on sharded tables, node_roles must be exactly one of "
                f"{sorted(r.name for r in DATA_NODE_ROLES)}"
            )
            # Satellite clusters are single-shard and live in __extra_hosts, which
            # map_one_host_per_shard cannot reach; any_host_by_roles can.
            if not is_local_or_test and single_role in SINGLE_SHARD_DATA_NODE_ROLES:
                logger.info("       Running ALTER on sharded replicated table on one host of role %s", single_role)
                return cluster.any_host_by_roles(query, node_roles=node_roles_list).result()
            return cluster.map_one_host_per_shard(query).result()
        elif is_alter_on_replicated_table:
            logger.info("       Running ALTER on replicated table on just one host")
            return cluster.any_host_by_roles(query, node_roles=node_roles_list).result()
        else:
            return cluster.map_hosts_by_roles(query, node_roles=node_roles_list, require_hosts=require_hosts).result()

    operation = migrations.RunPython(lambda _: run_migration())

    # Attach metadata for validation tools
    # Use original_node_roles (before debug override) for validation purposes
    operation._sql = sql
    operation._node_roles = original_node_roles
    # node_roles_list reflects the debug/hobby override (e.g. collapsed to NodeRole.ALL),
    # i.e. the roles this migration actually targets under the current settings.
    operation._effective_node_roles = node_roles_list
    operation._sharded = sharded
    operation._is_alter_on_replicated_table = is_alter_on_replicated_table
    operation._require_hosts = require_hosts
    operation._only_if_table_exists = only_if_table_exists

    return operation
