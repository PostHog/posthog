from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
]
