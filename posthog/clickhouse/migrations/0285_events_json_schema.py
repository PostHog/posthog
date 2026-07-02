from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE_SQL,
    EVENTS_JSON_TABLE_MV_SQL,
    EVENTS_JSON_TABLE_SQL,
    KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL,
    WRITABLE_EVENTS_JSON_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        EVENTS_JSON_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        WRITABLE_EVENTS_JSON_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_EVENTS_JSON_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL(on_cluster=False),
        node_roles=[NodeRole.DATA],
    ),
    # Dual-write MV: populates the native-JSON events table from the same Kafka topic as the
    # legacy events_json_mv, but through a dedicated consumer group so JSON-table retries can't
    # replay legacy writes.
    run_sql_with_exceptions(
        EVENTS_JSON_TABLE_MV_SQL(on_cluster=False),
        node_roles=[NodeRole.DATA],
    ),
]
