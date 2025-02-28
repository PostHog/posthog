from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.cluster import NodeRole
from posthog.models.exchange_rate.sql import (
    DROP_EXCHANGE_RATE_TABLE_SQL,
    DROP_EXCHANGE_RATE_DICTIONARY_SQL,
    EXCHANGE_RATE_TABLE_SQL,
    EXCHANGE_RATE_DATA_BACKFILL_SQL,
    EXCHANGE_RATE_DICTIONARY_SQL,
)

operations = [
    # Drop tables to allow this to rerun
    run_sql_with_exceptions(DROP_EXCHANGE_RATE_TABLE_SQL()),
    run_sql_with_exceptions(DROP_EXCHANGE_RATE_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    run_sql_with_exceptions(DROP_EXCHANGE_RATE_DICTIONARY_SQL()),
    run_sql_with_exceptions(DROP_EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    # Recreate them all
    run_sql_with_exceptions(EXCHANGE_RATE_TABLE_SQL()),
    run_sql_with_exceptions(EXCHANGE_RATE_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
    run_sql_with_exceptions(EXCHANGE_RATE_DATA_BACKFILL_SQL()),
    run_sql_with_exceptions(EXCHANGE_RATE_DATA_BACKFILL_SQL(), node_role=NodeRole.COORDINATOR),
    run_sql_with_exceptions(EXCHANGE_RATE_DICTIONARY_SQL()),
    run_sql_with_exceptions(EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR),
]
