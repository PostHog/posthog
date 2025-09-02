from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.cluster import NodeRole
from posthog.models.exchange_rate.sql import (
    DROP_EXCHANGE_RATE_DICTIONARY_SQL,
    DROP_EXCHANGE_RATE_TABLE_SQL,
    EXCHANGE_RATE_DATA_BACKFILL_SQL,
    EXCHANGE_RATE_DICTIONARY_SQL,
    EXCHANGE_RATE_TABLE_SQL,
)

# This is the exact same thing as 0101_add_exchange_rates.py,
# but it's a separate migration because we need to rerun it with some new changes
# to the database and dictionary query.
# Refer to git history to understand the changes.
operations = [
    # Drop tables/dictionaries to allow this to rerun
    # Dict first because it depends on the table
    run_sql_with_exceptions(
        DROP_EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(
        DROP_EXCHANGE_RATE_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    # Recreate them all
    run_sql_with_exceptions(
        EXCHANGE_RATE_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
    run_sql_with_exceptions(EXCHANGE_RATE_DATA_BACKFILL_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(
        EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=False), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ),
]
