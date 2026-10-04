from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.saved_query_reads import (
    SAVED_QUERY_READS_DAILY_STAGING_TABLE_SQL,
    SAVED_QUERY_READS_DAILY_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(SAVED_QUERY_READS_DAILY_TABLE_SQL(), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(SAVED_QUERY_READS_DAILY_STAGING_TABLE_SQL(), node_roles=[NodeRole.DATA]),
]
