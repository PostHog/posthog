from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.execute import sync_execute


def run_sql_with_exceptions(sql: str, settings={}):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    """

    def run_sql(database):
        sync_execute(sql, settings=settings)

    return migrations.RunPython(run_sql)
