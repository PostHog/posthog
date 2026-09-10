from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import (
    LOG_ATTRIBUTES3_TABLE_SQL,
    LOGS34_TO_LOG_ATTRIBUTES3_MV,
    LOGS34_TO_RESOURCE_ATTRIBUTES3_MV,
)

# log_attributes2 cannot gain severity_text in place: it is an AggregatingMergeTree whose sort key
# is its aggregation key, and MODIFY ORDER BY would re-key existing parts mid-flight. Instead we add
# a parallel log_attributes3 table that carries severity_text in its ORDER BY and back it with new
# MVs reading from logs34. Existing log_attributes2 and its MVs are left untouched, so ingestion keeps
# running and the read path can be cut over to log_attributes3 once it has backfilled.
operations = [
    run_sql_with_exceptions(LOG_ATTRIBUTES3_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_TO_LOG_ATTRIBUTES3_MV(), node_roles=[NodeRole.LOGS]),
    run_sql_with_exceptions(LOGS34_TO_RESOURCE_ATTRIBUTES3_MV(), node_roles=[NodeRole.LOGS]),
]
