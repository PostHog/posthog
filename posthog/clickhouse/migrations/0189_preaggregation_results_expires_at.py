from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.sql import (
    DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE,
    SHARDED_PREAGGREGATION_RESULTS_TABLE,
)

ADD_EXPIRES_AT_COLUMN = """
ALTER TABLE IF EXISTS {table}
ADD COLUMN IF NOT EXISTS expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY AFTER time_window_start
"""

ADD_TTL = """
ALTER TABLE IF EXISTS {table}
MODIFY TTL expires_at
"""

operations = [
    # Add expires_at column to sharded table
    run_sql_with_exceptions(
        ADD_EXPIRES_AT_COLUMN.format(table=SHARDED_PREAGGREGATION_RESULTS_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # Add TTL to sharded table
    run_sql_with_exceptions(
        ADD_TTL.format(table=SHARDED_PREAGGREGATION_RESULTS_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # Add expires_at column to distributed table
    run_sql_with_exceptions(
        ADD_EXPIRES_AT_COLUMN.format(table=DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
