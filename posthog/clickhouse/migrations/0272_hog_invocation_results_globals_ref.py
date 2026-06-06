from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.hog_invocation_results.sql import (
    DROP_HOG_INVOCATION_RESULTS_MV_SQL,
    HOG_INVOCATION_RESULTS_DATA_TABLE,
    HOG_INVOCATION_RESULTS_MV_SQL,
    HOG_INVOCATION_RESULTS_TABLE,
)

# Stop persisting `invocation_globals` in ClickHouse. The globals already travel
# in the results Kafka message (the producer still sends them), so the rerun path
# fetches them back by (partition, offset) from Warpstream's HTTP fetch endpoint
# instead — the message's coordinates are already recorded on every row via the
# Kafka engine's virtual `_partition`/`_offset` columns. That makes the large
# `invocation_globals` column dead weight on disk, so drop it.
#
# IMPORTANT: this bounds rerun reach by the results topic's retention. The topic
# retention must be >= the table TTL (HOG_INVOCATION_RESULTS_TTL_DAYS) so the
# whole rerun window is still fetchable.
#
# The Kafka engine table keeps `invocation_globals` (it still parses the field
# off the message); only the MV's projection and the persisted columns change, so
# only the MV is recreated here.
#
# `DROP COLUMN IF EXISTS` keeps this idempotent: on a fresh cluster the data
# table is created without the column (the updated CREATE SQL), so the drop is a
# no-op; on existing clusters the column from the original 0254 table is removed.
operations = [
    # Drop the MV first — it reads `invocation_globals` and writes it into the
    # data table, so it must go before the column is dropped.
    run_sql_with_exceptions(
        DROP_HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE IF EXISTS {HOG_INVOCATION_RESULTS_DATA_TABLE} DROP COLUMN IF EXISTS invocation_globals",
        node_roles=[NodeRole.AUX],
        is_alter_on_replicated_table=True,
    ),
    # Distributed read alias — present on both AUX and DATA.
    run_sql_with_exceptions(
        f"ALTER TABLE IF EXISTS {HOG_INVOCATION_RESULTS_TABLE} DROP COLUMN IF EXISTS invocation_globals",
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    # Recreate the MV without the `invocation_globals` projection.
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
