from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    LEGACY_QUERY_LOG_ARCHIVE_VIEWS,
    LEGACY_QUERY_LOG_ARCHIVE_WRITE_TABLES,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE_SQL,
    QUERY_LOG_ARCHIVE_V3_MV_SQL,
    SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE_SQL,
    WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE_SQL,
)
from posthog.run_mode import run_mode

# The query_log_archive suite on the OPS cluster, one aggregated row per query chain:
#   - sharded_query_log_archive_v3 and query_log_archive_v3_buffer on OPS.
#   - writable_query_log_archive_v3 and ops_query_log_archive_v3_mv on every cluster, so every cluster
#     archives its own system.query_log into OPS.
#   - query_log_archive, the Distributed read table over the v3 data table, everywhere.

ALL_ROLES = [
    NodeRole.DATA,
    NodeRole.ENDPOINTS,
    NodeRole.AUX,
    NodeRole.AI_EVENTS,
    NodeRole.SESSIONS,
    NodeRole.OPS,
]

operations = [
    *(
        []
        if run_mode().is_deployed_cloud
        else [
            # Drop the views first, so that no MV writes into a table this migration drops.
            *[
                run_sql_with_exceptions(f"DROP TABLE IF EXISTS {view}", node_roles=ALL_ROLES)
                for view in LEGACY_QUERY_LOG_ARCHIVE_VIEWS
            ],
            *[
                run_sql_with_exceptions(f"DROP TABLE IF EXISTS {table}", node_roles=ALL_ROLES)
                for table in LEGACY_QUERY_LOG_ARCHIVE_WRITE_TABLES
            ],
        ]
    ),
    run_sql_with_exceptions(SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE_SQL(), node_roles=[NodeRole.OPS]),
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE_SQL(), node_roles=[NodeRole.OPS]),
    run_sql_with_exceptions(WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE_SQL(), node_roles=ALL_ROLES),
    run_sql_with_exceptions(QUERY_LOG_ARCHIVE_V3_MV_SQL(), node_roles=ALL_ROLES),
    # An earlier generation used query_log_archive as a data table. Rename it aside, so that the read
    # table can take the name and no archived rows are lost.
    run_sql_with_exceptions(
        f"RENAME TABLE IF EXISTS {QUERY_LOG_ARCHIVE_DATA_TABLE} TO {QUERY_LOG_ARCHIVE_DATA_TABLE}_legacy",
        node_roles=[NodeRole.ALL],
    ),
    run_sql_with_exceptions(DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(), node_roles=[NodeRole.ALL]),
]
