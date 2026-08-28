from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# log_attributes2 is write-only. 0288 moved log_attributes_distributed to
# log_attributes3, so readers resolve the alias to 3 and only these two
# materialized views still write to 2.
#
# Order is load-bearing. A view whose target table is gone fails every insert
# into logs34, which stops the whole logs pipeline rather than attributes
# alone. Drop the writers first, then the table.
#
# max_table_size_to_drop = 0 lifts the server's drop-size guard, which
# otherwise refuses a table this large. SYNC releases the ZooKeeper path in
# the same step; log_attributes3 holds a separate path, so it is unaffected.

operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs34_to_log_attributes",
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs34_to_resource_attributes",
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.log_attributes2 SYNC SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.LOGS],
    ),
]
