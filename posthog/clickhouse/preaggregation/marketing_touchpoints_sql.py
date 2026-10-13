# Reusable, attribution-config-agnostic touchpoint precompute: one row per UTM-tagged
# pageview (team, person, timestamp + the tracked UTM dimensions). Unlike
# conversion_goal_attributed_preaggregated (which caches per-goal attribution RESULTS,
# keyed by job_id = goal+mode+window), this caches the raw touchpoints — the same job is
# shared across every attribution mode, window and goal, which all attribute at read time.


from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES,
)

TABLE_BASE_NAME = "marketing_touchpoints_preaggregated"

# Shared with the attributed table so both stay in lockstep with TRACKED_FIELDS.
MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES: list[str] = CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES


def DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_MARKETING_TOUCHPOINTS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_MARKETING_TOUCHPOINTS_TABLE()}"
