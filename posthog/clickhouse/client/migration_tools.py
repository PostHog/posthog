from typing import Union
from collections.abc import Callable

from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.execute import sync_execute


def run_sql_with_exceptions(sql: Union[str, Callable[[], str]], settings=None):
    """
    migrations.RunSQL does not raise exceptions, so we need to wrap it in a function that does.
    """

    if settings is None:
        settings = {}

    def run_sql(database):
        nonlocal sql
        if callable(sql):
            sql = sql()
        sync_execute(sql, settings=settings)

    return migrations.RunPython(run_sql)
