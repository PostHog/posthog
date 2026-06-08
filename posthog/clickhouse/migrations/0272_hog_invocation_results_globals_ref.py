from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.hog_invocation_results.sql import DROP_HOG_INVOCATION_RESULTS_MV_SQL, HOG_INVOCATION_RESULTS_MV_SQL

# Stop persisting `invocation_globals` in ClickHouse. The globals also travel in
# the results Kafka message (the producer still sends them), so the rerun path
# fetches them back by (partition, offset) from Warpstream's HTTP fetch endpoint
# instead — the message's coordinates are already recorded on every row via the
# Kafka engine's virtual `_partition`/`_offset` columns.
#
# The `invocation_globals` column is deliberately kept on the data table and
# distributed alias — only the MV changes so it no longer projects the field into
# the table. New rows leave the column empty; existing rows keep whatever was
# already written. Recreating the MV is therefore the only operation needed.
#
# IMPORTANT: this bounds rerun reach by the results topic's retention. The topic
# retention must be >= the table TTL (HOG_INVOCATION_RESULTS_TTL_DAYS) so the
# whole rerun window is still fetchable.
operations = [
    # Drop the MV first — the current MV writes `invocation_globals` into the data
    # table, so it must go before the replacement (which omits that column) lands.
    run_sql_with_exceptions(
        DROP_HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Recreate the MV without the `invocation_globals` projection.
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
