import logging

from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import get_cluster
from posthog.settings.data_stores import CLICKHOUSE_MIGRATIONS_CLUSTER

logger = logging.getLogger("migrations")


def run_sql_with_exceptions(sql: str, settings=None, node_role: NodeRole = NodeRole.WORKER):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    node_role is set to WORKER by default to keep compatibility with the old migrations.
    """

    cluster = get_cluster(client_settings=settings, cluster=CLICKHOUSE_MIGRATIONS_CLUSTER)

    def run_migration():
        if node_role == NodeRole.ALL:
            logger.info("       Running migration on coordinators and workers")
            return cluster.map_all_hosts(lambda client: client.execute(sql)).result()
        else:
            logger.info(f"       Running migration on {node_role.value.lower()}s")
            return cluster.map_hosts_by_role(lambda client: client.execute(sql), node_role=node_role).result()

    return migrations.RunPython(lambda _: run_migration())
