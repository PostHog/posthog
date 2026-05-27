# Pre-attributed output of the conversion-goal pipeline: one row per
# (team, job, person, conversion_timestamp, touchpoint_timestamp) with the
# attribution weight for that touchpoint. Single-touch emits weight=1.0 and one
# row per conversion; multi-touch emits N rows per conversion with fractional
# weights that sum to 1.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree

TABLE_BASE_NAME = "conversion_goal_attributed_preaggregated"

# Keep in lockstep with TRACKED_FIELDS in conversion_goal_processor.py.
# test_conversion_goal_processor_refactor.py enforces this.
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

    person_id UUID,
    conversion_timestamp DateTime64(6, 'UTC'),
    conversion_value Float64,

    touchpoint_timestamp DateTime64(6, 'UTC'),
    touchpoint_weight Float64,

    {_attributed_field_columns()}

    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {{engine}}
"""


def SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL():
    return (
        CONVERSION_GOAL_ATTRIBUTED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, person_id, conversion_timestamp, touchpoint_timestamp)
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
