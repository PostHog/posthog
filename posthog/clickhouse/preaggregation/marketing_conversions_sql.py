# Reusable, attribution-config-agnostic conversion precompute: one row per conversion event
# (team, person, timestamp, math value + the conversion-side tracked UTM dimensions). Sibling of
# marketing_touchpoints_preaggregated: touchpoints cache the pageview side, this caches the
# conversion side. Keyed by (event/action + filters + math) — not by attribution mode or window —
# so the same job is shared across every mode, window and view, which attribute at read time.

from django.conf import settings

from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES,
)
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree

TABLE_BASE_NAME = "marketing_conversions_preaggregated"

# Shared with the attributed/touchpoints tables so all stay in lockstep with TRACKED_FIELDS.
MARKETING_CONVERSIONS_TRACKED_FIELD_NAMES: list[str] = CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES


def DISTRIBUTED_MARKETING_CONVERSIONS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_MARKETING_CONVERSIONS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_MARKETING_CONVERSIONS_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, ver="computed_at")


def _conversion_field_columns() -> str:
    """Render one ``{name}_name String,`` per tracked field."""
    return "\n    ".join(f"{name}_name String," for name in MARKETING_CONVERSIONS_TRACKED_FIELD_NAMES)


MARKETING_CONVERSIONS_TABLE_BASE_SQL = f"""
CREATE TABLE IF NOT EXISTS {{table_name}}
(
    team_id Int64,
    job_id UUID,

    person_id UUID,
    conversion_timestamp DateTime64(6, 'UTC'),
    conversion_math_value Float64,
    session_id String,

    {_conversion_field_columns()}

    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {{engine}}
"""


def SHARDED_MARKETING_CONVERSIONS_TABLE_SQL():
    return (
        MARKETING_CONVERSIONS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, person_id, conversion_timestamp)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_MARKETING_CONVERSIONS_TABLE(),
        engine=SHARDED_MARKETING_CONVERSIONS_TABLE_ENGINE(),
    )


def DISTRIBUTED_MARKETING_CONVERSIONS_TABLE_SQL():
    return MARKETING_CONVERSIONS_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_MARKETING_CONVERSIONS_TABLE(),
        engine=Distributed(
            data_table=SHARDED_MARKETING_CONVERSIONS_TABLE(),
            sharding_key="cityHash64(person_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_MARKETING_CONVERSIONS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_MARKETING_CONVERSIONS_TABLE()}"


def DROP_SHARDED_MARKETING_CONVERSIONS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_MARKETING_CONVERSIONS_TABLE()} SYNC"


def TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_MARKETING_CONVERSIONS_TABLE()}"
