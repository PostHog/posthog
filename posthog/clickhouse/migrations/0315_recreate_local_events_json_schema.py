from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE_SQL,
    EVENTS_JSON_TABLE_MV_SQL,
    EVENTS_JSON_TABLE_SQL,
    KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL,
    WRITABLE_EVENTS_JSON_TABLE_SQL,
)
from posthog.run_mode import run_mode

operations = (
    []
    if run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS events_json_table_mv",
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS kafka_events_json_native_json",
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS writable_events_json",
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions("DROP TABLE IF EXISTS events_json", node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions("DROP TABLE IF EXISTS writable_events_json", node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(
            "DROP TABLE IF EXISTS sharded_events_json SYNC",
            node_roles=[NodeRole.DATA],
            sharded=True,
        ),
        run_sql_with_exceptions(EVENTS_JSON_TABLE_SQL(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(WRITABLE_EVENTS_JSON_TABLE_SQL(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DISTRIBUTED_EVENTS_JSON_TABLE_SQL(), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(
            WRITABLE_EVENTS_JSON_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL(on_cluster=False),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            EVENTS_JSON_TABLE_MV_SQL(on_cluster=False),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
)
