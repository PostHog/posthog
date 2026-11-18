"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.

Adds copies of the span_id and trace_id index projections that also store team_id, so a HogQL lookup (which
always filters on team_id) can be answered from a projection. The old projections stay. The new ones
are not materialized: parts written before this migration never get them and age out with retention.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.trace_spans ADD PROJECTION IF NOT EXISTS projection_index_team_span_id "
        "(SELECT team_id, _part_offset ORDER BY span_id)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.trace_spans ADD PROJECTION IF NOT EXISTS projection_index_team_trace_id "
        "(SELECT team_id, _part_offset ORDER BY trace_id)",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
