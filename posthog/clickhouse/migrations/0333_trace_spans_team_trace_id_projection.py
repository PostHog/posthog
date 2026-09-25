"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.

Parts written before this migration have no projection_index_team_trace_id. Backfilling it
(`MATERIALIZE PROJECTION`) rewrites every retained part, so it runs by hand, not here.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.trace_spans ADD PROJECTION IF NOT EXISTS projection_index_team_trace_id "
        "(SELECT _part_offset ORDER BY team_id, trace_id) WITH SETTINGS (index_granularity = 512)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
