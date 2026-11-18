from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.series_values_preaggregated_sql import (
    DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE_SQL,
    SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(SHARDED_SERIES_VALUES_PREAGGREGATED_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(
        DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.AUX]
    ),
]
