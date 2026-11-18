"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE adhoc_events_deletion ADD COLUMN IF NOT EXISTS data_deletion_request_id Nullable(UUID) AFTER uuid",
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
