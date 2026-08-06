from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.message_assets.sql import (
    DISTRIBUTED_MESSAGE_ASSETS_TABLE_SQL,
    KAFKA_MESSAGE_ASSETS_TABLE_SQL,
    MESSAGE_ASSETS_DATA_TABLE_SQL,
    MESSAGE_ASSETS_MV_SQL,
)

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
