from infi.clickhouse_orm import migrations

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.client import sync_execute
from posthog.models.event.sql import (
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

# Custom SQL for ClickHouse 25 compatibility - no consumer_breadcrumbs column
def EVENTS_TABLE_JSON_MV_SQL_NO_BREADCRUMBS():
    from posthog.models.event.sql import WRITABLE_EVENTS_DATA_TABLE
    from posthog import settings
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS events_json_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
person_id,
person_created_at,
person_properties,
group0_properties,
group1_properties,
group2_properties,
group3_properties,
group4_properties,
group0_created_at,
group1_created_at,
group2_created_at,
group3_created_at,
group4_created_at,
person_mode,
_timestamp,
_offset
FROM {database}.kafka_events_json
""".format(
        target_table=WRITABLE_EVENTS_DATA_TABLE(),
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )



# Column was added in 0057_events_person_mode
ALTER_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER {cluster}
MODIFY COLUMN person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)
"""


def alter_columns_in_required_tables(_):
    sync_execute(ALTER_COLUMNS_BASE_SQL.format(table="events", cluster=CLICKHOUSE_CLUSTER))
    sync_execute(ALTER_COLUMNS_BASE_SQL.format(table="writable_events", cluster=CLICKHOUSE_CLUSTER))
    sync_execute(ALTER_COLUMNS_BASE_SQL.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER))


operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunPython(alter_columns_in_required_tables),
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL_NO_BREADCRUMBS()),
]
