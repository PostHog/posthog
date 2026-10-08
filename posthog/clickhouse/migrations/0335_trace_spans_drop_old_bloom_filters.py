"""AUTO-GENERATED from the declarative HCL by posthog/clickhouse/hcl/codegen/gen_migration.py.
Placement (node_roles) is derived from the node composition manifest; review before committing.

Drops the 0.00001 false positive rate trace_id and span_id bloom filters, replaced by the smaller 0.05 ones
(idx_trace_bloom_part_v2 / idx_span_id_bloom_part_v2) added in 0334. Parts written before 0334 have no
trace_id / span_id bloom filter after this, until they age out with retention.
"""

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.trace_spans DROP INDEX IF EXISTS idx_trace_bloom_part, DROP INDEX IF EXISTS idx_span_id_bloom_part",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
