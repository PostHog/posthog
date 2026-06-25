from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics.metric_events import METRIC_EVENTS_DISTRIBUTED_TABLE_SQL, METRIC_EVENTS_TABLE_SQL

operations = [
    run_sql_with_exceptions(METRIC_EVENTS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(METRIC_EVENTS_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
]
