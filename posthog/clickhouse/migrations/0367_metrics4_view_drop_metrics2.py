from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRICS4_VIEW_SQL

operations = [
    run_sql_with_exceptions(METRICS4_VIEW_SQL(), node_roles=[NodeRole.LOGS]),
]
