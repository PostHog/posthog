# Table for storing the pre-attributed output of the conversion-goal pipeline.
#
# The previous design (conversion_goal_arrays_preaggregated) stored per-person
# arrays and re-merged them on read with arrayFlatten(groupArray(...)). That
# re-merge turned out to dominate read latency for small-to-medium teams,
# cancelling the benefit of caching.
#
# This table instead materialises the ARRAY JOIN + single-touch attribution at
# write time. Each row is a fully-attributed conversion: one row per
# (team, job, person, conversion_timestamp) with scalar UTM columns resolved to
# the touchpoint that attributed. Reads are a flat SELECT ... WHERE job_id IN
# (...) + date filter + GROUP BY drill-down field. No array work, no re-merge.
#
# Trade-off: the grain now depends on attribution_mode (single-touch only here).
# Multi-touch modes fall back to the direct path for now; a future iteration can
# add a sibling table with per-touchpoint rows + weights.
#
# See products/marketing_analytics/backend/hogql_queries/LAZY_COMPUTATION_PLAN.md
# for the full design.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree

TABLE_BASE_NAME = "conversion_goal_attributed_preaggregated"

# Keep in lockstep with TRACKED_FIELDS in
# products/marketing_analytics/backend/hogql_queries/conversion_goal_processor.py.
# A test in test_conversion_goal_processor_refactor.py enforces this.
CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES: list[str] = [
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


def DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, ver="computed_at")


def _attributed_field_columns() -> str:
    """Render one ``{name}_name String,`` per tracked field."""
    return "\n    ".join(f"{name}_name String," for name in CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES)


CONVERSION_GOAL_ATTRIBUTED_TABLE_BASE_SQL = f"""
CREATE TABLE IF NOT EXISTS {{table_name}}
(
    team_id Int64,
    job_id UUID,

    -- One row per conversion event, post-attribution.
    person_id UUID,
    conversion_timestamp DateTime64(6, 'UTC'),
    conversion_value Float64,

    -- Attributed UTM values. For single-touch: the values from the attributed
    -- touchpoint (or empty strings if organic — the read path applies
    -- organic defaults before the final GROUP BY).
    {_attributed_field_columns()}

    -- When this row was computed (used as ReplacingMergeTree version)
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- TTL: rows are automatically deleted after expires_at
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {{engine}}
"""


def SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL():
    return (
        CONVERSION_GOAL_ATTRIBUTED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, person_id, conversion_timestamp)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE(),
        engine=SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE_ENGINE(),
    )


def DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL():
    return CONVERSION_GOAL_ATTRIBUTED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE(),
            sharding_key="cityHash64(person_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE()}"


def DROP_SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE()} SYNC"


def TRUNCATE_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE()}"
