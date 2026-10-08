from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Same shape as 0342: the new column joins the end of the sort key in the ALTER that adds it,
# so this is metadata only. Existing parts read metric_type as '' and leave by TTL.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_names "
        "ADD COLUMN IF NOT EXISTS metric_type LowCardinality(String), "
        "MODIFY ORDER BY (team_id, time_bucket, metric_name, original_expiry_time_bucket, service_name, metric_type)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_metrics4_names ADD COLUMN IF NOT EXISTS metric_type LowCardinality(String)",
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
    metric_type
FROM {DB}.metrics4_input AS input
WHERE has_labels
GROUP BY team_id, time_bucket, metric_name, original_expiry_time_bucket, service_name, metric_type""",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
