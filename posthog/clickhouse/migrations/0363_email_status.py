from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import (
    DISTRIBUTED_EMAIL_STATUS_TABLE_SQL,
    EMAIL_STATUS_DATA_TABLE_SQL,
    EMAIL_STATUS_MV_SQL,
    KAFKA_EMAIL_STATUS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        EMAIL_STATUS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        KAFKA_EMAIL_STATUS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        EMAIL_STATUS_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_EMAIL_STATUS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
