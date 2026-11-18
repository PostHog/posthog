"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.

Adds copies of the per-part trace_id and span_id bloom filters with a 0.05 false positive rate instead of
0.00001. The filter is approx. 70% smaller, and the time to load it costs a lookup much more than the extra
false positives. The old indices stay. The new ones are not materialized: parts written before this
migration never get them and age out with retention.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.trace_spans "
        "ADD INDEX IF NOT EXISTS idx_trace_bloom_part_v2 trace_id TYPE bloom_filter(0.05) GRANULARITY 99999, "
        "ADD INDEX IF NOT EXISTS idx_span_id_bloom_part_v2 span_id TYPE bloom_filter(0.05) GRANULARITY 99999",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
