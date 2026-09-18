"""Derived from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.

The sorting key statement is hand-written: codegen reports a key change as a
recreate, but ClickHouse accepts a column appended to the sorting key when the
same ALTER adds the column, which keeps the rollup's history.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import LOGS34_TO_VOLUME_BUCKETS_MV_SELECT

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Rows written before this migration read as `retention_days` 0, so they keep
# the 42 day floor. The primary key stays the six dimensions it already covers:
# MODIFY ORDER BY leaves it alone, and declaring it holds a table created from
# scratch identical to one this migration altered.
ADD_RETENTION_DAYS = f"""
ALTER TABLE {DB}.logs_volume_buckets
    ADD COLUMN IF NOT EXISTS retention_days UInt16 AFTER severity_text,
    MODIFY ORDER BY (team_id, time_bucket, service_name, namespace, environment, severity_text, retention_days)
"""

# The TTL materialization is skipped: it rewrites every existing part to reach
# the same 42 day expiry those rows already carry.
MODIFY_TTL = f"""
ALTER TABLE {DB}.logs_volume_buckets
    MODIFY TTL time_bucket + toIntervalDay(greatest(42, retention_days))
    SETTINGS materialize_ttl_after_modify = 0
"""

ADD_RETENTION_DAYS_DISTRIBUTED = f"""
ALTER TABLE {DB}.logs_volume_buckets_distributed
    ADD COLUMN IF NOT EXISTS retention_days UInt16 AFTER severity_text
"""

operations = [
    run_sql_with_exceptions(
        ADD_RETENTION_DAYS,
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        MODIFY_TTL,
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_RETENTION_DAYS_DISTRIBUTED,
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
