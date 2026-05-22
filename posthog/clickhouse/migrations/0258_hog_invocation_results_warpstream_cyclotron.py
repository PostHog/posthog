from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.hog_invocation_results.sql import (
    DROP_HOG_INVOCATION_RESULTS_MV_SQL,
    DROP_KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL,
    HOG_INVOCATION_RESULTS_MV_SQL,
    KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL,
)

# Repoint the hog_invocation_results Kafka engine table from the warpstream-shared
# named collection to warpstream-cyclotron. The CDP producer writes lifecycle
# rows to the cyclotron Warpstream cluster, so ClickHouse must consume from the
# same cluster. The Kafka engine table and MV are non-replicated, so a plain
# drop + recreate is safe (no SYNC needed); the data table is untouched.
operations = [
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
]
