from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.hog_invocation_results.sql import (
    DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL,
    HOG_INVOCATION_RESULTS_DATA_TABLE_SQL,
    HOG_INVOCATION_RESULTS_MV_SQL,
    HOG_INVOCATION_RESULTS_WS_MV_SQL,
    KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL,
    KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE_SQL,
    WRITABLE_HOG_INVOCATION_RESULTS_TABLE_SQL,
)

_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")


operations = [
    # 1. Sharded source-of-truth on data nodes. ReplacingMergeTree on
    #    (team_id, function_kind, function_id, invocation_id) — lifecycle rows
    #    for the same invocation collapse via the `version` column at merge time.
    run_sql_with_exceptions(
        HOG_INVOCATION_RESULTS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    # 2. Distributed read alias on data nodes. HogQL queries point here.
    run_sql_with_exceptions(
        DISTRIBUTED_HOG_INVOCATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # 3. Distributed write alias on the ingestion layer — the MV writes here,
    #    rows are routed by cityHash64(invocation_id) so all rows for the same
    #    invocation land on the same shard (so ReplacingMergeTree can merge them).
    run_sql_with_exceptions(
        WRITABLE_HOG_INVOCATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 4. Kafka engine table + MV. Cloud uses the WarpStream-backed pair, all
    #    other deployments use the MSK pair. Same shape, different consumer
    #    group + named collection.
    *(
        [
            run_sql_with_exceptions(
                KAFKA_HOG_INVOCATION_RESULTS_WS_TABLE_SQL(),
                node_roles=[NodeRole.INGESTION_SMALL],
            ),
            run_sql_with_exceptions(
                HOG_INVOCATION_RESULTS_WS_MV_SQL(),
                node_roles=[NodeRole.INGESTION_SMALL],
            ),
        ]
        if _is_cloud
        else [
            run_sql_with_exceptions(
                KAFKA_HOG_INVOCATION_RESULTS_TABLE_SQL(),
                node_roles=[NodeRole.INGESTION_SMALL],
            ),
            run_sql_with_exceptions(
                HOG_INVOCATION_RESULTS_MV_SQL(),
                node_roles=[NodeRole.INGESTION_SMALL],
            ),
        ]
    ),
]
