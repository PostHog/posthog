from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.group.sql import (
    DROP_GROUPS_TABLE_MV_SQL,
    DROP_KAFKA_GROUPS_TABLE_SQL,
    GROUPS_TABLE_MV_SQL,
    GROUPS_WRITABLE_TABLE_SQL,
    KAFKA_GROUPS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_GROUPS_TABLE_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_GROUPS_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(GROUPS_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_GROUPS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(GROUPS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
]
