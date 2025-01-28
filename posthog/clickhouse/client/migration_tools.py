from clickhouse_driver import Client
from infi.clickhouse_orm import migrations

from posthog.clickhouse.cluster import get_cluster


def run_sql_with_exceptions(sql: str, settings=None):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    """

    cluster = get_cluster(client_settings=settings)

    def run_sql(client: Client):
        return migrations.RunPython(lambda _: client.execute(sql))

    return cluster.any_host(run_sql).result()
