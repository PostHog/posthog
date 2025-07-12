from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
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


ADD_COLUMNS_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER '{cluster}'
MODIFY COLUMN IF EXISTS inserted_at DEFAULT NOW64()
"""

DROP_COLUMN_BASE_SQL = """
ALTER TABLE {table}
ON CLUSTER '{cluster}'
DROP COLUMN IF EXISTS inserted_at
"""


operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(ADD_COLUMNS_BASE_SQL.format(table="events", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(DROP_COLUMN_BASE_SQL.format(table="writable_events", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(ADD_COLUMNS_BASE_SQL.format(table="sharded_events", cluster=CLICKHOUSE_CLUSTER)),
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL_NO_BREADCRUMBS()),
]
