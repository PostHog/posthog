"""Adds an hourly per-service freshness projection to metrics4_samples.

The projection is not materialized. New parts and merges build it, and the overview query that reads it reads only
recent hours. Parts with and without the projection do not merge together, so the parts that exist at deploy time
merge only with each other until TTL drops them.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    # A settings-only ALTER changes only the replica that runs it, so this runs on every host.
    # ADD PROJECTION on an AggregatingMergeTree fails until this setting is in place.
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples MODIFY SETTING deduplicate_merge_projection_mode = 'rebuild'",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"""
ALTER TABLE {DB}.metrics4_samples ADD PROJECTION IF NOT EXISTS service_freshness_by_hour
(
    SELECT
        team_id,
        time_bucket,
        service_name,
        max(arrayMax(timestamp_arr))
    GROUP BY team_id, time_bucket, service_name
)
""",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
