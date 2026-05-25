from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_goals_preaggregated_sql import (
    DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL,
)

operations = [
    # Sharded data table on AUX — matches the convention of migrations 0256 / 0259 / 0260 / 0261.
    run_sql_with_exceptions(
        SHARDED_WEB_GOALS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read table on DATA.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
