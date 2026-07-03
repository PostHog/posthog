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

# The native-JSON events tables are always created so deletion/mutation mirroring can rely on
# them existing. The Kafka consumer + dual-write MV are only created when
# CLICKHOUSE_EVENTS_JSON_DUAL_WRITE is enabled: consuming the full events topic a second time
# doubles events ingestion and storage, which upgrading (especially self-hosted) instances must
# opt into. Enabling later without re-running this migration:
# `manage.py manage_events_json_dual_write --start`.
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
    # The dual-write MV runs on the events ingestion layer (like the legacy events pipeline,
    # see 0238/0160) and writes through this writable table, so it must exist there too.
    run_sql_with_exceptions(
        WRITABLE_EVENTS_JSON_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_EVENTS],
    ),
]

if settings.CLICKHOUSE_EVENTS_JSON_DUAL_WRITE:
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
