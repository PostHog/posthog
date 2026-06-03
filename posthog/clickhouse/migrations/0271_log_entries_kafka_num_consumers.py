from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import (
    DROP_KAFKA_LOG_ENTRIES_WS_TABLE_SQL,
    DROP_LOG_ENTRIES_WS_MV_SQL,
    KAFKA_LOG_ENTRIES_WS_TABLE_SQL,
    LOG_ENTRIES_WS_MV_SQL,
)

# Recreate the WarpStream log_entries Kafka table + MV with kafka_num_consumers = 16 to
# match the live cluster; the table definition had no setting so code defaulted to 1.
# Kafka engine and MV are not replicated, so the drops do not need SYNC.
operations = [
    run_sql_with_exceptions(DROP_LOG_ENTRIES_WS_MV_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_KAFKA_LOG_ENTRIES_WS_TABLE_SQL, node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_LOG_ENTRIES_WS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(LOG_ENTRIES_WS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]
