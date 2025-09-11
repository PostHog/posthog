from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries_v2_test import (
    KAFKA_LOG_ENTRIES_V2_TABLE_SQL,
    LOG_ENTRIES_V2_TABLE_MV_SQL,
    LOG_ENTRIES_V2_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(KAFKA_LOG_ENTRIES_V2_TABLE_SQL(on_cluster=False)),
    run_sql_with_exceptions(
        LOG_ENTRIES_V2_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(LOG_ENTRIES_V2_TABLE_MV_SQL(on_cluster=False)),
]
