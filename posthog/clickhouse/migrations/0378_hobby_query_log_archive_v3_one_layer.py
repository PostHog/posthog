from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL,
    LEGACY_QUERY_LOG_ARCHIVE_VIEWS,
    LEGACY_QUERY_LOG_ARCHIVE_WRITE_TABLES,
    QUERY_LOG_ARCHIVE_DATA_TABLE,
    QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE,
    QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE_SQL,
    QUERY_LOG_ARCHIVE_V3_MV,
    QUERY_LOG_ARCHIVE_V3_MV_SQL,
    SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE_SQL,
    WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE_SQL,
)
from posthog.run_mode import RunMode, run_mode

# Hobby installs that applied 0273 before it built the v3 archive still write through the earlier
# generation. This migration moves every hobby install to the v3 write path that 0273 builds today,
# and gives the v3 Buffer one layer. Each Buffer layer flushes on its own once max_time passes, so on
# an idle install 16 layers write many small parts where one layer writes one part.
#
# Every statement is IF EXISTS or IF NOT EXISTS, so a run that stops at any statement can run again
# from the start and reach the same schema.


def drop(table: str, node_roles: list[NodeRole]):
    return run_sql_with_exceptions(f"DROP TABLE IF EXISTS {table}", node_roles=node_roles)


operations = (
    [
        # Drop the views first, so that no MV writes into a table this migration drops.
        *[drop(view, [NodeRole.ALL]) for view in (*LEGACY_QUERY_LOG_ARCHIVE_VIEWS, QUERY_LOG_ARCHIVE_V3_MV)],
        # A Buffer flushes its rows into its destination table when it is dropped.
        *[drop(table, [NodeRole.ALL]) for table in LEGACY_QUERY_LOG_ARCHIVE_WRITE_TABLES],
        drop(QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE, [NodeRole.OPS]),
        # Every version of 0273 made query_log_archive a Distributed table, which stores no rows.
        # The earlier generation's copy reads the earlier data table, so it is replaced.
        drop(QUERY_LOG_ARCHIVE_DATA_TABLE, [NodeRole.ALL]),
        run_sql_with_exceptions(SHARDED_QUERY_LOG_ARCHIVE_V3_TABLE_SQL(), node_roles=[NodeRole.OPS]),
        run_sql_with_exceptions(QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE_SQL(num_layers=1), node_roles=[NodeRole.OPS]),
        run_sql_with_exceptions(WRITABLE_QUERY_LOG_ARCHIVE_V3_TABLE_SQL(), node_roles=[NodeRole.ALL]),
        run_sql_with_exceptions(DISTRIBUTED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL(), node_roles=[NodeRole.ALL]),
        run_sql_with_exceptions(QUERY_LOG_ARCHIVE_V3_MV_SQL(), node_roles=[NodeRole.ALL]),
    ]
    if run_mode() is RunMode.HOBBY
    else []
)
