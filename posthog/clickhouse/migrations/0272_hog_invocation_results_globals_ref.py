from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.hog_invocation_results.sql import (
    DROP_HOG_INVOCATION_RESULTS_MV_SQL,
    HOG_INVOCATION_RESULTS_DATA_TABLE,
    HOG_INVOCATION_RESULTS_MV_SQL,
    HOG_INVOCATION_RESULTS_TABLE,
)

# Record a (partition, offset) reference back to the Kafka message that carries
# each row's `invocation_globals`, so the rerun path can fetch the globals from
# Warpstream's HTTP fetch endpoint by reference instead of persisting the large
# blob in ClickHouse for 30 days.
#
# The columns are materialized by the MV from the Kafka engine's virtual
# `_partition`/`_offset` columns (see HOG_INVOCATION_RESULTS_MV_SQL). The Kafka
# engine table is unchanged — these are not part of the message body — so unlike
# 0258 there's no Kafka table to recreate. We only:
#   1. Add the columns to the local data table and the distributed read alias.
#   2. Recreate the MV (non-replicated) so new rows populate them.
#
# `invocation_globals` is intentionally retained: existing rows still carry it,
# and the rerun read path falls back to it for rows written before this change
# (and while the topic retention is being raised to match the table's TTL). A
# follow-up migration drops the column once the by-reference path is the only
# reader.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE IF EXISTS {HOG_INVOCATION_RESULTS_DATA_TABLE} "
        "ADD COLUMN IF NOT EXISTS globals_partition UInt64 DEFAULT 0 AFTER is_deleted",
        node_roles=[NodeRole.AUX],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE IF EXISTS {HOG_INVOCATION_RESULTS_DATA_TABLE} "
        "ADD COLUMN IF NOT EXISTS globals_offset UInt64 DEFAULT 0 AFTER globals_partition",
        node_roles=[NodeRole.AUX],
        is_alter_on_replicated_table=True,
    ),
    # Distributed read alias — present on both AUX and DATA so HogQL/replay reads
    # resolve the columns. Distributed engine isn't replicated, so no flag.
    run_sql_with_exceptions(
        f"ALTER TABLE IF EXISTS {HOG_INVOCATION_RESULTS_TABLE} "
        "ADD COLUMN IF NOT EXISTS globals_partition UInt64 AFTER is_deleted",
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE IF EXISTS {HOG_INVOCATION_RESULTS_TABLE} "
        "ADD COLUMN IF NOT EXISTS globals_offset UInt64 AFTER globals_partition",
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    # Recreate the MV (kafka -> data table) so it materializes the new columns
    # from the Kafka virtual `_partition`/`_offset`. MV is non-replicated — plain
    # DROP + CREATE, no SYNC needed.
    run_sql_with_exceptions(
        DROP_HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
