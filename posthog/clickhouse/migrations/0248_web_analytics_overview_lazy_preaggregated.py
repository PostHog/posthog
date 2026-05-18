from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_analytics_overview_lazy_sql import (
    DISTRIBUTED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL,
    SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
