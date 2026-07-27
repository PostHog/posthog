from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.hog_invocation_results.sql import (
    DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL,
    DROP_HOG_INVOCATION_RESULTS_MV_SQL,
    DROP_KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL,
    HOG_INVOCATION_RESULTS_DATA_TABLE_SQL,
    HOG_INVOCATION_RESULTS_MV_SQL,
    KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL,
)

# Repoint the hog_invocation_results Kafka engine table from the warpstream-shared
# named collection to warpstream-cyclotron — the CDP producer writes lifecycle
# rows to the cyclotron Warpstream cluster, so ClickHouse must consume from the
# same cluster.
#
# The Kafka engine table + MV are non-replicated, so they're dropped and
# recreated outright (no SYNC needed). The data table and distributed read
# alias are re-asserted with CREATE ... IF NOT EXISTS first: 0254 creates them,
# but a cluster that lost its AUX local tables (e.g. a rebuilt dev AUX cluster)
# still has 0254 recorded as applied — leaving the MV recreate below to fail
# with "table does not exist". IF NOT EXISTS makes the re-assert a no-op
# wherever the tables are already present.
operations = [
    # Ensure the local data table the MV targets exists.
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Drop the MV first — it reads from the Kafka engine table.
    run_sql_with_exceptions(
        DROP_HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Drop + recreate the Kafka engine table on the warpstream-cyclotron collection.
    run_sql_with_exceptions(
        DROP_KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Recreate the MV (kafka -> data table).
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Ensure the distributed read alias exists (HogQL queries resolve through it).
    run_sql_with_exceptions(
        DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
