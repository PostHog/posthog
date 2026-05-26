"""Drop the redundant `web_stats_preaggregated` Distributed table from AUX.

Migration 0259 created the Distributed routing table on both DATA and AUX. The
AUX-side definition was added for ad-hoc operator debugging convenience, but
nothing in production reads or writes through it — the lazy precompute path
issues all queries via the DATA-side Distributed (which already forwards to
the AUX-resident sharded table).

The other two web preagg tables (0256_web_overview_preaggregated and
0260_web_stats_paths_preaggregated) follow the original convention: sharded on
AUX, Distributed on DATA only. This migration aligns `web_stats_preaggregated`
with that convention so all three web preagg tables have an identical layout.

Distributed engines hold no data — dropping the AUX-side table only removes
the routing metadata. The sharded table on AUX is untouched.
"""

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS web_stats_preaggregated SYNC SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.AUX],
    ),
]
