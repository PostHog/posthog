from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import (
    METRICS4_INPUT_TO_METRICS4_SERVICE_FRESHNESS_MV,
    METRICS4_SERVICE_FRESHNESS_TABLE_SQL,
    WRITABLE_METRICS4_SERVICE_FRESHNESS_TABLE_SQL,
)

# No backfill: the table starts empty, and readers keep the series last_seen when it has no row for a service.
operations = [
    run_sql_with_exceptions(METRICS4_SERVICE_FRESHNESS_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(WRITABLE_METRICS4_SERVICE_FRESHNESS_TABLE_SQL(), node_roles=[NodeRole.APM]),
    run_sql_with_exceptions(METRICS4_INPUT_TO_METRICS4_SERVICE_FRESHNESS_MV(), node_roles=[NodeRole.APM]),
]
