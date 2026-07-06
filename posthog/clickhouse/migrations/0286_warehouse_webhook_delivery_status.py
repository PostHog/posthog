from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.warehouse_webhook_delivery_status.sql import (
    DISTRIBUTED_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL,
    KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL,
    WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE_SQL,
    WAREHOUSE_WEBHOOK_DELIVERY_STATUS_MV_SQL,
)

# Layout mirrors `hog_invocation_results` — an AUX-resident, non-sharded family
# backed by the warpstream-cyclotron named collection (the same cluster the CDP
# node produces to).
operations = [
    # 1. Local replicated data table on AUX.
    run_sql_with_exceptions(
        WAREHOUSE_WEBHOOK_DELIVERY_STATUS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 2. Kafka engine table on AUX (warpstream-cyclotron).
    run_sql_with_exceptions(
        KAFKA_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 3. MV on AUX (kafka -> data table).
    run_sql_with_exceptions(
        WAREHOUSE_WEBHOOK_DELIVERY_STATUS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 4. Distributed read alias on AUX and DATA so the data import pipeline can
    #    query the bare name from either cluster.
    run_sql_with_exceptions(
        DISTRIBUTED_WAREHOUSE_WEBHOOK_DELIVERY_STATUS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
