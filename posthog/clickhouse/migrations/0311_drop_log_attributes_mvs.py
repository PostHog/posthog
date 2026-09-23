from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# These two views are the only writers left to log_attributes2. 0288 pointed
# log_attributes_distributed at log_attributes3, so readers reach 3 through the
# alias and nothing consumes what these views produce.
#
# Dropping them stops the write and replication load straight away. The table
# stays, so this step is reversible: the SQL to recreate both views sits in
# 0280, which created them.

operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs34_to_log_attributes",
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs34_to_resource_attributes",
        node_roles=[NodeRole.LOGS],
    ),
]
