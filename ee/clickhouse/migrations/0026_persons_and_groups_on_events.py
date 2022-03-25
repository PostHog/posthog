from infi.clickhouse_orm import migrations

from ee.clickhouse.replication.utils import clickhouse_is_replicated
from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER

ADD_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS person_id UUID,
ADD COLUMN IF NOT EXISTS person_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group0_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group1_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group2_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group3_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group4_properties VARCHAR
"""


def add_columns_to_sharded_tabled_if_nedded(_):
    if clickhouse_is_replicated():
        sync_execute(ADD_COLUMNS_BASE_SQL.format(table="writable_events", cluster=CLICKHOUSE_CLUSTER))
        sync_execute(ADD_COLUMNS_BASE_SQL.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    migrations.RunSQL(ADD_COLUMNS_BASE_SQL.format(table="events", cluster=CLICKHOUSE_CLUSTER)),
    migrations.RunPython(add_columns_to_sharded_tabled_if_nedded),
]
