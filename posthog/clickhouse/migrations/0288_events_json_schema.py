from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE_SQL,
    EVENTS_JSON_TABLE_MV_SQL,
    EVENTS_JSON_TABLE_SQL,
    KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL,
    WRITABLE_EVENTS_JSON_TABLE_SQL,
)

_IS_CLOUD = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

# Cloud clusters get this schema rolled out separately. Keep this migration empty there so
# merging the application code does not change production ClickHouse schema.
operations = (
    []
    if _IS_CLOUD
    else [
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
        # The dual-write MV runs on the events ingestion layer (like the legacy events pipeline,
        # see 0238/0160) and writes through this writable table, so it must exist there too.
        run_sql_with_exceptions(
            WRITABLE_EVENTS_JSON_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
)

if not _IS_CLOUD and settings.CLICKHOUSE_EVENTS_JSON_DUAL_WRITE:
    operations += [
        run_sql_with_exceptions(
            KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL(on_cluster=False),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        # Dual-write MV: populates the native-JSON events table from the same Kafka topic as the
        # legacy events_json_mv, but through a dedicated consumer group so JSON-table retries can't
        # replay legacy writes.
        run_sql_with_exceptions(
            EVENTS_JSON_TABLE_MV_SQL(on_cluster=False),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
