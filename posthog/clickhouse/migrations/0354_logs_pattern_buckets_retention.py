from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    # Nothing writes to logs_pattern_buckets yet, so the TTL change has no existing
    # parts to rewrite.
    run_sql_with_exceptions(
        f"""
ALTER TABLE {DB}.logs_pattern_buckets
    ADD COLUMN IF NOT EXISTS retention_days SimpleAggregateFunction(max, UInt16) AFTER pattern,
    MODIFY TTL time_bucket + toIntervalDay(greatest(42, retention_days))
    SETTINGS materialize_ttl_after_modify = 0
""",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_pattern_buckets MODIFY SETTING ttl_only_drop_parts = 0",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.logs_pattern_buckets_distributed "
        "ADD COLUMN IF NOT EXISTS retention_days SimpleAggregateFunction(max, UInt16) AFTER pattern",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
