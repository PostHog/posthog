from typing import Dict

from infi.clickhouse_orm import migrations, RunPython

from posthog.clickhouse.client.execute import sync_execute


def run_sql_with_exceptions(sql: str, settings=Dict | None) -> RunPython:
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    """

    if settings is None:
        settings = {}

    def run_sql(database):
        sync_execute(sql, settings=settings)

    return migrations.RunPython(run_sql)
