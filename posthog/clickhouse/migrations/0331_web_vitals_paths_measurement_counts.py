"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE posthog.sharded_web_vitals_paths_preaggregated ADD COLUMN IF NOT EXISTS inp_count UInt64 AFTER fcp_quantiles_state, ADD COLUMN IF NOT EXISTS lcp_count UInt64 AFTER inp_count, ADD COLUMN IF NOT EXISTS cls_count UInt64 AFTER lcp_count, ADD COLUMN IF NOT EXISTS fcp_count UInt64 AFTER cls_count",
        node_roles=[NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE posthog.web_vitals_paths_preaggregated ADD COLUMN IF NOT EXISTS inp_count UInt64 AFTER fcp_quantiles_state, ADD COLUMN IF NOT EXISTS lcp_count UInt64 AFTER inp_count, ADD COLUMN IF NOT EXISTS cls_count UInt64 AFTER lcp_count, ADD COLUMN IF NOT EXISTS fcp_count UInt64 AFTER cls_count",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
