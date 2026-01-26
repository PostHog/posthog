from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from products.tasks.backend.sql import (
    AGENT_LOGS_DATA_TABLE_SQL,
    AGENT_LOGS_MV_SQL,
    AGENT_LOGS_WRITABLE_TABLE_SQL,
    KAFKA_AGENT_LOGS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        AGENT_LOGS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        AGENT_LOGS_WRITABLE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        KAFKA_AGENT_LOGS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        AGENT_LOGS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
