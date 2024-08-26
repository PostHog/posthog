from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import ch_pool
from posthog.settings import CLICKHOUSE_CLUSTER


DROP_COLUMNS_SHARDED_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
DROP COLUMN IF EXISTS is_deleted
"""

ADD_COLUMNS_SHARDED_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS is_deleted Boolean DEFAULT False
"""


def add_columns_to_required_tables(_):
    with ch_pool.get_client() as client:
        client.execute(DROP_COLUMNS_SHARDED_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))
        client.execute(ADD_COLUMNS_SHARDED_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
