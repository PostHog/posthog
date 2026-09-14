"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE posthog.logs_volume_buckets "
        "ADD COLUMN IF NOT EXISTS retention_days UInt16 DEFAULT 42, "
        "MODIFY TTL time_bucket + toIntervalDay(least(retention_days, 42))",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE posthog.logs_volume_buckets_distributed ADD COLUMN IF NOT EXISTS retention_days UInt16 DEFAULT 42",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE posthog.logs_pattern_buckets "
        "ADD COLUMN IF NOT EXISTS retention_days UInt16 DEFAULT 42, "
        "MODIFY TTL time_bucket + toIntervalDay(least(retention_days, 42))",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE posthog.logs_pattern_buckets_distributed "
        "ADD COLUMN IF NOT EXISTS retention_days UInt16 DEFAULT 42",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
