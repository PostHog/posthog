import logging
from functools import cache
from typing import Optional

from infi.clickhouse_orm import migrations

from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import Query, get_cluster
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER, CLICKHOUSE_MIGRATIONS_HOST

logger = logging.getLogger("migrations")


@cache
def get_migrations_cluster():
    return get_cluster(host=CLICKHOUSE_MIGRATIONS_HOST, cluster=CLICKHOUSE_MIGRATIONS_CLUSTER)


def run_sql_with_exceptions(
    sql: str,
    node_roles: list[NodeRole] | NodeRole | None = None,
    sharded: Optional[bool] = None,
    is_alter_on_replicated_table: Optional[bool] = None,
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
        In general, run everything on NodeRole.DATA and NodeRole.COORDINATOR except changes to sharded tables / writable distributed tables.
    sharded: bool, optional (default is False)
        Indicates if the migration is on a sharded table
    is_alter_on_replicated_table: bool, optional (default is False)
        Specifies whether the query is an ALTER statement executed on replicated tables.
        This will run on just one host per shard or one host for the whole cluster if there is no sharding.

    Returns:
    migrations.RunPython
        A high-level representation capable of running the migration query in the specified
        context, including its distribution across nodes based on input parameters.

    Raises:
    AssertionError
        Raised in certain scenarios when the input arguments conflict with the expected
        configuration, such as when the sharded flag is set for roles other than DATA.
    """

    if node_roles and not isinstance(node_roles, list):
        node_roles = [node_roles]

    node_roles = node_roles or [NodeRole.DATA]

    # Store original node_roles for validation purposes before debug override
    original_node_roles = node_roles

    if settings.E2E_TESTING or settings.DEBUG:
        # In E2E tests and debug mode, we run migrations on ALL nodes
        # because we don't have different ClickHouse topologies yet in Docker
        node_roles = [NodeRole.ALL]

    errors = []
    if "ON CLUSTER" in sql:
        logger.error("ON CLUSTER is not supposed to used in migration, query: %s", sql)
    if "ALTER TABLE" in sql:
        if sharded is None:
            errors.append("sharded parameter must be explicitly specified for ALTER TABLE queries")
        if is_alter_on_replicated_table is None:
            errors.append("is_alter_on_replicated_table parameter must be explicitly specified for ALTER TABLE queries")
    if errors:
        msg = "\n\t- ".join(errors)
        raise ValueError(f"problems:\n\t- {msg}")

    def run_migration():
        cluster = get_migrations_cluster()

        query = Query(sql)
        if sharded:
            assert (NodeRole.DATA in node_roles and len(node_roles) == 1) or (
                settings.E2E_TESTING or settings.DEBUG
            ), "When running migrations on sharded tables, the node_role must be NodeRole.DATA"
            return cluster.map_one_host_per_shard(query).result()
        elif is_alter_on_replicated_table:
            logger.info("       Running ALTER on replicated table on just one host")
            return cluster.any_host_by_roles(query, node_roles=node_roles).result()
        else:
            return cluster.map_hosts_by_roles(query, node_roles=node_roles).result()

    operation = migrations.RunPython(lambda _: run_migration())

    # Attach metadata for validation tools
    # Use original_node_roles (before debug override) for validation purposes
    operation._sql = sql
    operation._node_roles = original_node_roles
    operation._sharded = sharded
    operation._is_alter_on_replicated_table = is_alter_on_replicated_table

    return operation
