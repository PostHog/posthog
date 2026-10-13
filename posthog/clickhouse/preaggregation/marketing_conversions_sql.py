# Reusable, attribution-config-agnostic conversion precompute: one row per conversion event
# (team, person, timestamp, math value + the conversion-side tracked UTM dimensions). Sibling of
# marketing_touchpoints_preaggregated: touchpoints cache the pageview side, this caches the
# conversion side. Keyed by (event/action + filters + math) — not by attribution mode or window —
# so the same job is shared across every mode, window and view, which attribute at read time.


from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES,
)

TABLE_BASE_NAME = "marketing_conversions_preaggregated"

# Shared with the attributed/touchpoints tables so all stay in lockstep with TRACKED_FIELDS.
MARKETING_CONVERSIONS_TRACKED_FIELD_NAMES: list[str] = CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES


def DISTRIBUTED_MARKETING_CONVERSIONS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_MARKETING_CONVERSIONS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_MARKETING_CONVERSIONS_TABLE()}"
