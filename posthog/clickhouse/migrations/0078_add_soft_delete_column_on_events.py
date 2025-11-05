from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.settings import CLICKHOUSE_CLUSTER

DROP_COLUMNS_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
DROP COLUMN IF EXISTS is_deleted
"""

ADD_COLUMNS_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD COLUMN IF NOT EXISTS is_deleted Boolean
"""

ADD_COLUMNS_INDEX_EVENTS = """
ALTER TABLE {table} ON CLUSTER {cluster}
ADD INDEX IF NOT EXISTS is_deleted_idx (is_deleted) TYPE minmax GRANULARITY 1
"""


def add_columns_to_required_tables(_):
    with get_client_from_pool() as client:
        client.execute(DROP_COLUMNS_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))
        client.execute(DROP_COLUMNS_EVENTS.format(table="events", cluster=CLICKHOUSE_CLUSTER))
        client.execute(ADD_COLUMNS_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))
        client.execute(ADD_COLUMNS_EVENTS.format(table="events", cluster=CLICKHOUSE_CLUSTER))
        client.execute(ADD_COLUMNS_INDEX_EVENTS.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunPython(add_columns_to_required_tables),
]
