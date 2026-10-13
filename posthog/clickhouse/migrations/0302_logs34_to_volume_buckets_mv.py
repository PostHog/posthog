from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import LOGS34_TO_VOLUME_BUCKETS_MV

operations = [
    run_sql_with_exceptions(LOGS34_TO_VOLUME_BUCKETS_MV(), node_roles=[NodeRole.LOGS]),
]
