from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.message_assets.sql import (
    DISTRIBUTED_MESSAGE_ASSETS_TABLE_SQL,
    KAFKA_MESSAGE_ASSETS_TABLE_SQL,
    MESSAGE_ASSETS_DATA_TABLE_SQL,
    MESSAGE_ASSETS_MV_SQL,
)

# Stores compact metadata for every successfully sent workflow email — the
# rendered HTML body itself lives in object storage at `s3_key`. Mirrors the
# `hog_invocation_results` layout: AUX-resident, single shard, fed by the CDP
# cyclotron Warpstream cluster, 30-day TTL.
#   * Local replicated data table on AUX.
#   * Single Kafka engine table on AUX (warpstream-cyclotron named collection).
#   * MV on AUX, kafka -> local data table.
#   * Distributed read alias on AUX + DATA (the assets API + HogQL hit this).
operations = [
    run_sql_with_exceptions(
        MESSAGE_ASSETS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        KAFKA_MESSAGE_ASSETS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        MESSAGE_ASSETS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_MESSAGE_ASSETS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
