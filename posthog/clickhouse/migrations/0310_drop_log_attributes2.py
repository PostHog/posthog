from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# 0309 dropped the two views that wrote here, so the table has taken no writes
# since. Readers reach log_attributes3 through log_attributes_distributed.
#
# The table is far larger than the server's max_table_size_to_drop guard, so
# the drop sets the guard to 0 for this statement. SYNC releases the ZooKeeper
# path in the same step; log_attributes3 holds a separate path and is
# unaffected.

operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.log_attributes2 SYNC SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.LOGS],
    ),
]
