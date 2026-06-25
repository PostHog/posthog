from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.marketing_conversions_sql import (
    DISTRIBUTED_MARKETING_CONVERSIONS_TABLE_SQL,
    SHARDED_MARKETING_CONVERSIONS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_MARKETING_CONVERSIONS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_MARKETING_CONVERSIONS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
