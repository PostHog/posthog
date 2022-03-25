from infi.clickhouse_orm import migrations

from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.settings.data_stores import CLICKHOUSE_DATABASE, CLICKHOUSE_REPLICATION

ADD_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER '{cluster}'
ADD COLUMN IF NOT EXISTS person_id UUID,
ADD COLUMN IF NOT EXISTS person_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group0_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group1_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group2_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group3_properties VARCHAR,
ADD COLUMN IF NOT EXISTS group4_properties VARCHAR;
"""

operations = [
    migrations.RunSQL(ADD_COLUMNS_BASE_SQL.format(table="events", cluster=CLICKHOUSE_CLUSTER)),
]


if CLICKHOUSE_REPLICATION:

    # CLICKHOUSE_REPLICATION may be turned on but the instance might still
    # be on the old schema if it didn't run the sharding async migration (0004_replicated_schema)
    verify_table_exists_result = sync_execute(
        f"""
            SELECT count(*) from system.tables WHERE database='{CLICKHOUSE_DATABASE}' and name='writable_events'
        """
    )

    if verify_table_exists_result[0][0] > 0:
        extra_operations = [
            migrations.RunSQL(ADD_COLUMNS_BASE_SQL.format(table="writable_events", cluster=CLICKHOUSE_CLUSTER)),
            migrations.RunSQL(ADD_COLUMNS_BASE_SQL.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER)),
        ]

        operations += extra_operations
