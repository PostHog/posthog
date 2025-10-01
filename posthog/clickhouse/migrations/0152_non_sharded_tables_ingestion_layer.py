from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.plugin_log_entries import (
    DROP_KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    DROP_PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
    KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL,
    PLUGIN_LOG_ENTRIES_TABLE_MV_SQL,
    PLUGIN_LOG_ENTRIES_WRITABLE_TABLE_SQL,
)
from posthog.models.person.sql import (
    DROP_KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    DROP_KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
    DROP_KAFKA_PERSONS_TABLE_SQL,
    DROP_PERSON_DISTINCT_ID2_TABLE_MV_SQL,
    DROP_PERSON_DISTINCT_ID_OVERRIDES_TABLE_MV_SQL,
    DROP_PERSONS_TABLE_MV_SQL,
    KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL,
    KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    PERSON_DISTINCT_ID2_MV_SQL,
    PERSON_DISTINCT_ID2_WRITABLE_TABLE_SQL,
    PERSON_DISTINCT_ID_OVERRIDES_MV_SQL,
    PERSON_DISTINCT_ID_OVERRIDES_WRITABLE_TABLE_SQL,
    PERSONS_TABLE_MV_SQL,
    PERSONS_WRITABLE_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_PERSON_DISTINCT_ID2_TABLE_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PERSON_DISTINCT_ID2_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(
        KAFKA_PERSON_DISTINCT_ID2_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(PERSON_DISTINCT_ID2_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_PERSON_DISTINCT_ID_OVERRIDES_TABLE_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PERSON_DISTINCT_ID_OVERRIDES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(
        KAFKA_PERSON_DISTINCT_ID_OVERRIDES_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(
        PERSON_DISTINCT_ID_OVERRIDES_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(DROP_PLUGIN_LOG_ENTRIES_TABLE_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PLUGIN_LOG_ENTRIES_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(
        KAFKA_PLUGIN_LOG_ENTRIES_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]
    ),
    run_sql_with_exceptions(PLUGIN_LOG_ENTRIES_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DROP_PERSONS_TABLE_MV_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_PERSONS_TABLE_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(PERSONS_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_PERSONS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(PERSONS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.INGESTION_SMALL]),
]
