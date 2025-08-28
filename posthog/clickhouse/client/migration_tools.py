import logging
from functools import cache

from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import Query, get_cluster
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER, CLICKHOUSE_MIGRATIONS_HOST

logger = logging.getLogger("migrations")


@cache
def get_migrations_cluster():
    return get_cluster(host=CLICKHOUSE_MIGRATIONS_HOST, cluster=CLICKHOUSE_MIGRATIONS_CLUSTER)


def run_sql_with_exceptions(
    sql: str,
    node_role: NodeRole = NodeRole.DATA,
    sharded: bool = False,
    is_alter_on_replicated_table: bool = False,
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
    node_role: NodeRole to execute the migration on, optional (default is NodeRole.DATA is not specified)
        Specifies which type of node the query should target during execution.
        In general, run everything on NodeRole.ALL except changes to sharded tables / writable distributed tables.
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

    def run_migration():
        if "ON CLUSTER" in sql:
            logger.error("ON CLUSTER is not supposed to used in migration, query: %s", sql)

        cluster = get_migrations_cluster()

        query = Query(sql)
        if sharded:
            assert (
                node_role == NodeRole.DATA
            ), "When running migrations on sharded tables, the node_role must be NodeRole.DATA"
            return cluster.map_one_host_per_shard(query).result()
        elif is_alter_on_replicated_table:
            logger.info("       Running ALTER on replicated table on just one host")
            return cluster.any_host(query, node_role=node_role).result()
        else:
            return cluster.map_hosts_by_role(query, node_role=node_role).result()

    return migrations.RunPython(lambda _: run_migration())
