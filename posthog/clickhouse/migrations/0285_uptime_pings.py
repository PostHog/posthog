from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.uptime.backend.sql import (
    DISTRIBUTED_UPTIME_PINGS_TABLE_SQL,
    KAFKA_UPTIME_PINGS_TABLE_SQL,
    SHARDED_UPTIME_PINGS_TABLE_SQL,
    UPTIME_PINGS_MV_SQL,
    WRITABLE_UPTIME_PINGS_TABLE_SQL,
)

# Single-shot migration that sets up the Kafka -> MV -> sharded table pipeline used by
# rust/uptime-pinger. Ping volume is tiny (one row per monitor per interval), so the
# whole pipeline lives on the main cluster's data nodes rather than the ingestion layer.
operations = [
    run_sql_with_exceptions(
        SHARDED_UPTIME_PINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_UPTIME_PINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        WRITABLE_UPTIME_PINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        KAFKA_UPTIME_PINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        UPTIME_PINGS_MV_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
