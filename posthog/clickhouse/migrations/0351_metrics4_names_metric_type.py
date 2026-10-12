from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Not in the sort key: 0327 builds the table from the current SQL, so a longer key would make 0342's
# MODIFY ORDER BY fail on a fresh cluster. The set union on merge keeps every type a name was sent as.
# Existing parts read an empty array and leave by TTL.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_names "
        "ADD COLUMN IF NOT EXISTS metric_types SimpleAggregateFunction(groupUniqArrayArray, Array(String)), "
        "ADD COLUMN IF NOT EXISTS metric_type String ALIAS metric_types[1]",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_metrics4_names "
        "ADD COLUMN IF NOT EXISTS metric_types SimpleAggregateFunction(groupUniqArrayArray, Array(String))",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"""ALTER TABLE {DB}.metrics4_input_to_metrics4_names MODIFY QUERY
SELECT
    team_id,
    metric_name,
    toStartOfHour(timestamp) AS time_bucket,
    toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
    maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp,
    service_name,
    groupUniqArrayArraySimpleState([toString(metric_type)]) AS metric_types
FROM {DB}.metrics4_input AS input
WHERE has_labels
GROUP BY team_id, time_bucket, metric_name, original_expiry_time_bucket, service_name""",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
