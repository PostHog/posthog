from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Promote two OTel attributes — `posthog.session_id` and `posthog.distinct_id` —
# to indexed materialized columns on `logs32` and `trace_spans`. Filtering spans/logs
# by PostHog identity is a hot query path (session replay → related backend spans,
# error tracking → backend context). Today it scans `attributes_map_str`; this
# migration makes it a sub-second lookup via bloom-filter skip indexes.
#
# Attributes are stored in `attributes_map_str` with a `_str` key suffix
# (see the `attributes` alias in logs32.py / spans.py which strips it).
#
# Safety notes:
# - MATERIALIZED columns are computed at INSERT time only. Existing rows return ''.
# - ADD INDEX without MATERIALIZE INDEX applies to new parts only — no rewrite,
#   no merge storm on the live logs cluster.
# - Distributed tables get plain ALTER ADD COLUMN (no DROP/RECREATE) so reads
#   remain available throughout. Same pattern as migrations 0213 and 0218.

ADD_POSTHOG_IDENTITY_COLUMNS_REPLICATED = """
ALTER TABLE IF EXISTS {table}
    ADD COLUMN IF NOT EXISTS posthog_session_id String MATERIALIZED attributes_map_str['posthog.session_id__str'] CODEC(ZSTD(1)),
    ADD COLUMN IF NOT EXISTS posthog_distinct_id String MATERIALIZED attributes_map_str['posthog.distinct_id__str'] CODEC(ZSTD(1)),
    ADD INDEX IF NOT EXISTS idx_posthog_session_id posthog_session_id TYPE bloom_filter(0.01) GRANULARITY 1,
    ADD INDEX IF NOT EXISTS idx_posthog_distinct_id posthog_distinct_id TYPE bloom_filter(0.01) GRANULARITY 1
"""

ADD_POSTHOG_IDENTITY_COLUMNS_DISTRIBUTED = """
ALTER TABLE IF EXISTS {table}
    ADD COLUMN IF NOT EXISTS posthog_session_id String DEFAULT '',
    ADD COLUMN IF NOT EXISTS posthog_distinct_id String DEFAULT ''
"""

operations = [
    # 1. ALTER the underlying replicated tables — add the columns + skip indexes.
    #    `is_alter_on_replicated_table=True` ensures the ALTER runs once and
    #    replication propagates it (per AGENTS.md).
    run_sql_with_exceptions(
        ADD_POSTHOG_IDENTITY_COLUMNS_REPLICATED.format(table="trace_spans"),
        node_roles=[NodeRole.LOGS],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_POSTHOG_IDENTITY_COLUMNS_REPLICATED.format(table="logs32"),
        node_roles=[NodeRole.LOGS],
        is_alter_on_replicated_table=True,
    ),
    # 2. ALTER the Distributed read tables in place — no drop, no downtime.
    #    Distributed tables route queries and hold no data; they need the
    #    column declaration to forward selects to the underlying replicated table.
    run_sql_with_exceptions(
        ADD_POSTHOG_IDENTITY_COLUMNS_DISTRIBUTED.format(table="trace_spans_distributed"),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        ADD_POSTHOG_IDENTITY_COLUMNS_DISTRIBUTED.format(table="logs"),
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        ADD_POSTHOG_IDENTITY_COLUMNS_DISTRIBUTED.format(table="logs_distributed"),
        node_roles=[NodeRole.LOGS],
    ),
]
