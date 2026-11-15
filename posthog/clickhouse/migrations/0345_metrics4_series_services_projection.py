"""Adds an hourly per-service rollup projection to metrics4_series.

The projection is not materialized. New parts and merges build it, and the queries it serves read only recent hours.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    # A settings-only ALTER changes only the replica that runs it, so this runs on every host.
    # ADD PROJECTION on a ReplacingMergeTree fails until this setting is in place.
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_series MODIFY SETTING deduplicate_merge_projection_mode = 'rebuild'",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"""
ALTER TABLE {DB}.metrics4_series ADD PROJECTION IF NOT EXISTS services_by_hour
(
    SELECT
        team_id,
        time_bucket,
        service_name,
        uniqExact(metric_name),
        uniq(series_fingerprint),
        max(timestamp)
    GROUP BY team_id, time_bucket, service_name
)
""",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
