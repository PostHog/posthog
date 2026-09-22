from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import LOGS34_TO_VOLUME_BUCKETS_MV_SELECT

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    # Rows written before this runs read as `retention_days` 0, so greatest(42, 0)
    # reproduces the TTL they already carry. materialize_ttl_after_modify would
    # rewrite every part to arrive back at its current state, so it is turned off.
    run_sql_with_exceptions(
        f"""
ALTER TABLE {DB}.logs_volume_buckets
    ADD COLUMN IF NOT EXISTS retention_days SimpleAggregateFunction(max, UInt16) AFTER severity_text,
    MODIFY TTL time_bucket + toIntervalDay(greatest(42, retention_days))
    SETTINGS materialize_ttl_after_modify = 0
""",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_volume_buckets MODIFY SETTING ttl_only_drop_parts = 0",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_volume_buckets_distributed "
        "ADD COLUMN IF NOT EXISTS retention_days SimpleAggregateFunction(max, UInt16) AFTER severity_text",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs34_to_volume_buckets MODIFY QUERY\n{LOGS34_TO_VOLUME_BUCKETS_MV_SELECT()}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
