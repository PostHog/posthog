"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples "
        "ADD COLUMN IF NOT EXISTS timestamp_min DateTime64(6) ALIAS arrayMin(timestamp_arr), "
        "ADD COLUMN IF NOT EXISTS timestamp_max DateTime64(6) ALIAS arrayMax(timestamp_arr), "
        "ADD INDEX IF NOT EXISTS idx_timestamp_min_minmax timestamp_min TYPE minmax GRANULARITY 1, "
        "ADD INDEX IF NOT EXISTS idx_timestamp_max_minmax timestamp_max TYPE minmax GRANULARITY 1",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
