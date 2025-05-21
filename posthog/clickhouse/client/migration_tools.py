from functools import cache
import logging

from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import Query, get_cluster
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER

logger = logging.getLogger("migrations")


@cache
def get_migrations_cluster():
    return get_cluster(cluster=CLICKHOUSE_MIGRATIONS_CLUSTER)


def run_sql_with_exceptions(
    sql: str, node_role: NodeRole = NodeRole.DATA, sharded: bool = False, is_alter_on_replicated_table: bool = False
):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    node_role is set to DATA by default to keep compatibility with the old migrations.

    sql: str - the SQL to run
    node_role: NodeRole - the role of the nodes to run the migration on. In general, run everything on NodeRole.ALL except changes to sharded tables / writable distributed tables.
    sharded: bool - whether the migration is on a sharded table
    is_alter_on_replicated_table: bool - whether the migration is an ALTER TABLE on a replicated table. This will run on just one host per shard or one host for the whole cluster if there is no sharding.
    """
    cluster = get_migrations_cluster()

    def run_migration():
        query = Query(sql)
        if node_role == NodeRole.ALL:
            assert not sharded
            logger.info("       Running migration on coordinators and data nodes")
            if is_alter_on_replicated_table:
                return cluster.any_host(query).result()
            else:
                return cluster.map_all_hosts(query).result()
        else:
            logger.info("       Running migration on %ss", node_role.value.lower())
            if sharded:
                assert node_role == NodeRole.DATA
                futures = cluster.map_one_host_per_shard(query)
            else:
                futures = cluster.map_hosts_by_role(query, node_role=node_role)
            return futures.result()

    return migrations.RunPython(lambda _: run_migration())
