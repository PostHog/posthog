# Pre-attributed output of the conversion-goal pipeline: one row per
# (team, job, person, conversion_timestamp, touchpoint_timestamp) with the
# attribution weight for that touchpoint. Single-touch emits weight=1.0 and one
# row per conversion; multi-touch emits N rows per conversion with fractional
# weights that sum to 1.


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


def SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE()}"
