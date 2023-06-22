from infi.clickhouse_orm import migrations
from django.conf import settings

from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_COLUMNS_BASE_SQL = """
ALTER TABLE `{database}`.`{table}`
ON CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS inserted_at DateTime64(6, 'UTC') DEFAULT NOW()
"""


def add_columns_to_required_tables(_):
    """
    We need to add the inserted_at column to the `sharded_events` table as it
    needs to be stored here, and we also want to be able to query it in a
    distributed fashion, so we add it to the `events` table as well.
    """
    sync_execute(
        ADD_COLUMNS_BASE_SQL.format(
            table="sharded_events", database=settings.CLICKHOUSE_DATABASE, cluster=CLICKHOUSE_CLUSTER
        )
    )
    sync_execute(
        ADD_COLUMNS_BASE_SQL.format(table="events", database=settings.CLICKHOUSE_DATABASE, cluster=CLICKHOUSE_CLUSTER)
    )


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
