from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL,
    DROP_SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL,
    DROP_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL,
)

# Repartition `web_overview_preaggregated` so `ttl_only_drop_parts=1` can drop
# expired parts atomically (the prior monthly partition keyed on `time_window_start`
# kept short-TTL rows alive alongside long-TTL rows in the same part).
#
# The table was added in migration 0257 and has not been served to any real
# team yet, so a clean drop+recreate is safe — no precomputed data is lost
# that can't be re-generated on the next read.

operations = [
    run_sql_with_exceptions(
        DROP_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DROP_SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
