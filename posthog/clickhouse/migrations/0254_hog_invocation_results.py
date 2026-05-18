from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.hog_invocation_results.sql import (
    DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL,
    HOG_INVOCATION_RESULTS_DATA_TABLE_SQL,
    HOG_INVOCATION_RESULTS_MV_SQL,
    KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL,
)

# Layout (mirrors `property_values`):
#   * Local replicated data table on the AUX cluster (1 shard, 2 replicas).
#   * Single Kafka engine table on AUX, backed by the warpstream-shared named
#     collection — one topic, one consumer group. No MSK pair.
#   * MV on AUX, kafka → local data table.
#   * Distributed read alias on AUX + DATA (replay and HogQL queries hit this).
operations = [
    # 1. Local replicated data table on AUX.
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 2. Kafka engine table on AUX (warpstream-shared).
    run_sql_with_exceptions(
        KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 3. MV on AUX (kafka -> data table).
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 4. Distributed read alias on AUX and DATA so both cluster's queries reach
    #    the data. HogQL emits the bare name `hog_invocation_results`; this
    #    alias is what resolves it.
    run_sql_with_exceptions(
        DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
