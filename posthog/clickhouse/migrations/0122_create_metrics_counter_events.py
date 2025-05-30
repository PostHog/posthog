from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.clickhouse.custom_metrics import CREATE_METRICS_COUNTER_EVENTS_TABLE

operations = [run_sql_with_exceptions(CREATE_METRICS_COUNTER_EVENTS_TABLE, node_role=NodeRole.ALL)]
