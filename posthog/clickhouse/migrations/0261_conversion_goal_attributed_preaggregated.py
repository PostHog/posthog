# Historical migration: creates the per-goal attributed preagg table. The table is dropped in
# migration 0268; the source SQL helpers (posthog/clickhouse/preaggregation/conversion_goal_attributed_sql.py)
# were removed in the same PR, so this migration inlines its SQL to remain loadable on fresh DBs.

from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree

TABLE_BASE_NAME = "conversion_goal_attributed_preaggregated"
TRACKED_FIELD_NAMES: list[str] = [
    "campaign",
    "source",
    "medium",
    "content",
    "term",
    "referring_domain",
    "gclid",
    "fbclid",
    "gad_source",
]
_FIELD_COLUMNS = "\n    ".join(f"{name}_name String," for name in TRACKED_FIELD_NAMES)

_BASE_SQL = f"""
CREATE TABLE IF NOT EXISTS {{table_name}}
(
    team_id Int64,
    job_id UUID,

    person_id UUID,
    conversion_timestamp DateTime64(6, 'UTC'),
    conversion_value Float64,

    touchpoint_timestamp DateTime64(6, 'UTC'),
    touchpoint_weight Float64,

    {_FIELD_COLUMNS}

    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {{engine}}
"""

SHARDED_SQL = (
    _BASE_SQL
    + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, person_id, conversion_timestamp, touchpoint_timestamp)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
).format(
    table_name=f"sharded_{TABLE_BASE_NAME}",
    engine=ReplacingMergeTree(TABLE_BASE_NAME, ver="computed_at"),
)

DISTRIBUTED_SQL = _BASE_SQL.format(
    table_name=TABLE_BASE_NAME,
    engine=Distributed(
        data_table=f"sharded_{TABLE_BASE_NAME}",
        sharding_key="cityHash64(person_id)",
        cluster=settings.CLICKHOUSE_AUX_CLUSTER,
    ),
)

operations = [
    run_sql_with_exceptions(SHARDED_SQL, node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(DISTRIBUTED_SQL, node_roles=[NodeRole.AUX, NodeRole.DATA]),
]
