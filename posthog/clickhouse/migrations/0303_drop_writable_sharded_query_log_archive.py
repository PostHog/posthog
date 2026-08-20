from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE

# writable_sharded_query_log_archive is the Distributed proxy migration 0196 created on
# ENDPOINTS so those nodes could write into the sharded table on the data cluster. 0273
# replaced that write path: it dropped dist_query_log_archive_mv, the proxy's only writer,
# and pointed every cluster at writable_query_log_archive instead. The proxy has had no
# writer and no reader since.
#
# 0273 already drops it off cloud, but it is applied everywhere, so editing it cannot reach
# a deployment that has already run it. Hence this migration.
#
# NodeRole.ALL rather than ENDPOINTS: 0196 put it there, but the table is to be gone from
# every node, and a Distributed proxy holds no data of its own.

operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {SHARDED_QUERY_LOG_ARCHIVE_WRITABLE_TABLE}",
        node_roles=[NodeRole.ALL],
    ),
]
