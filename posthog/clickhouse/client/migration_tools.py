import logging

from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import Query, get_cluster
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER

logger = logging.getLogger("migrations")

cluster = get_cluster(cluster=CLICKHOUSE_MIGRATIONS_CLUSTER)


def run_sql_with_exceptions(sql: str, node_role: NodeRole = NodeRole.DATA, sharded: bool = False):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    node_role is set to DATA by default to keep compatibility with the old migrations.
    """
    if sharded:
        assert node_role == NodeRole.DATA

    def run_migration():
        query = Query(sql)
        if node_role == NodeRole.ALL:
            logger.info("       Running migration on coordinators and data nodes")
            return cluster.map_all_hosts(query).result()
        elif node_role == NodeRole.DATA:
            logger.info("       Running migration on %ss (sharded: %s)", node_role.value.lower(), sharded)
            if sharded:
                futures = cluster.map_one_host_per_shard(query)
            else:
                futures = cluster.map_hosts_by_role(query, node_role=node_role)
            return futures.result()
        else:
            raise NotImplementedError

    return migrations.RunPython(lambda _: run_migration())
