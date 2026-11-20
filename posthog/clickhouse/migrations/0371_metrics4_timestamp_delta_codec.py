from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# A codec change only updates the table metadata. New parts and merges write timestamp_arr with Delta.
# Existing parts keep DoubleDelta until a merge rewrites them.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples MODIFY COLUMN IF EXISTS timestamp_arr "
        "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6))) CODEC(Delta, Default)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
