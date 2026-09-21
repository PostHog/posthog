from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations_v3 import ADD_EMAILS, ADD_FLAG_KEY_VALUES, ADD_HOSTS
from posthog.models.raw_sessions.sessions_v3 import (
    KAFKA_RAW_SESSIONS_V3_TABLE_SQL,
    RAW_SESSIONS_V3_EVENTS_WS_MV_SQL,
    WRITABLE_RAW_SESSIONS_TABLE_SQL_V3,
    WRITABLE_RAW_SESSIONS_TABLE_V3,
)
from posthog.run_mode import run_mode

# Recreates the sessions v3 live ingestion pipeline on the ingestion-events cluster under
# fresh ws2 names. Consumption starts when this migration applies: the MV attaches to the
# Kafka table and writes through the writable into the sessions cluster.
#
# The writable already exists in prod (hand-created, repointed at the sessions cluster), so
# its CREATE no-ops there and the ALTERs bring it up to the current column set. Local and
# hobby have no ingestion-events nodes and no WarpStream, so the pipeline is cloud-only,
# like the events_json_ws pipeline it mirrors.
operations = (
    []
    if not run_mode().is_deployed_cloud
    else [
        run_sql_with_exceptions(
            WRITABLE_RAW_SESSIONS_TABLE_SQL_V3(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            ADD_FLAG_KEY_VALUES.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
            node_roles=[NodeRole.INGESTION_EVENTS],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        run_sql_with_exceptions(
            ADD_HOSTS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
            node_roles=[NodeRole.INGESTION_EVENTS],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        run_sql_with_exceptions(
            ADD_EMAILS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
            node_roles=[NodeRole.INGESTION_EVENTS],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        run_sql_with_exceptions(
            KAFKA_RAW_SESSIONS_V3_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            RAW_SESSIONS_V3_EVENTS_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
)
