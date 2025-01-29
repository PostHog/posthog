import logging

from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import NodeType, Workload
from posthog.clickhouse.cluster import get_cluster
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER

logger = logging.getLogger("migrations")


def run_sql_with_exceptions(
    sql: str, settings=None, node_type: NodeType = NodeType.WORKER, workload: Workload = Workload.DEFAULT
):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    """

    cluster = get_cluster(client_settings=settings, cluster=CLICKHOUSE_MIGRATIONS_CLUSTER)

    def run_migration():
        if node_type == NodeType.DEFAULT:
            logger.info("       Running operation on coordinator and workers")
            return cluster.map_all_hosts(lambda client: client.execute(sql)).result()
        elif node_type == NodeType.COORDINATOR:
            logger.info("       Running operation on coordinator")
            return cluster.any_host(lambda client: client.execute(sql)).result()
        elif node_type == NodeType.WORKER:
            logger.info("       Running operation on worker")
            pass

    return migrations.RunPython(lambda _: run_migration())
