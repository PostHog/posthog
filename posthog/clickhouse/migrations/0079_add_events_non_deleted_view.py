from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.connection import ch_pool
from posthog.settings import CLICKHOUSE_CLUSTER

from posthog.models.event.sql import DISTRIBUTED_EVENTS_TABLE, EVENTS_NON_DELETED_VIEW_SQL


RENAME_EVENTS_TABLE = """
RENAME TABLE {table} TO {new_table} ON CLUSTER {cluster}
"""


def add_events_non_deleted_view(_):
    with ch_pool.get_client() as client:
        client.execute(RENAME_EVENTS_TABLE.format(table="events", new_table=DISTRIBUTED_EVENTS_TABLE(), cluster=CLICKHOUSE_CLUSTER))
        client.execute(EVENTS_NON_DELETED_VIEW_SQL())


operations = [
    migrations.RunPython(add_events_non_deleted_view),
]
