from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import (
    QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE,
    QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE_SQL,
)
from posthog.run_mode import RunMode, run_mode

# Each Buffer layer flushes on its own once max_time passes. On an idle hobby install every one of the
# 16 layers flushes every 60 seconds, which writes 16 small parts a minute into the replicated data
# table. One layer is enough for the query volume of a single install.
# DROP flushes the buffered rows to the data table. Rows archived in the moment between the two
# statements can be lost; system.query_log keeps the originals.
operations = (
    [
        run_sql_with_exceptions(f"DROP TABLE IF EXISTS {QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE}", node_roles=[NodeRole.OPS]),
        run_sql_with_exceptions(QUERY_LOG_ARCHIVE_V3_BUFFER_TABLE_SQL(num_layers=1), node_roles=[NodeRole.OPS]),
    ]
    if run_mode() is RunMode.HOBBY
    else []
)
