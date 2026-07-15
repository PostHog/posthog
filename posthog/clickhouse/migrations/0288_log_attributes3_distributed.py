from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import LOG_ATTRIBUTES3_DISTRIBUTED_TABLE_SQL

# Cut the shared log_attributes_distributed read path over to log_attributes3, which carries
# severity_text in its ORDER BY. log_attributes3 and its MVs are created and backfilled by migration
# 0282; this CREATE OR REPLACE repoints the distributed table once that data is in place.
operations = [
    run_sql_with_exceptions(LOG_ATTRIBUTES3_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
]
