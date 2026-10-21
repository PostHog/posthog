"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_DATABASE

# The index is not materialized here. MATERIALIZE INDEX on sharded_events reads every part of the
# table, so it runs as a separate manual operation. Until it runs, only parts written or merged
# after this migration carry the index.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.sharded_events "
        "ADD INDEX IF NOT EXISTS minmax_sharded_events_inserted_at inserted_at TYPE minmax GRANULARITY 1",
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
