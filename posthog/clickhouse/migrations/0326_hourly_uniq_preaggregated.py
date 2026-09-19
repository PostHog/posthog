from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.hourly_uniq_sql import HOURLY_UNIQ_TABLE_SQL, SHARDED_HOURLY_UNIQ_TABLE_SQL

operations = [
    run_sql_with_exceptions(SHARDED_HOURLY_UNIQ_TABLE_SQL(), node_roles=[NodeRole.DATA], sharded=True),
    run_sql_with_exceptions(HOURLY_UNIQ_TABLE_SQL(), node_roles=[NodeRole.DATA]),
]
