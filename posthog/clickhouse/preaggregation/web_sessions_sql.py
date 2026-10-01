# Session-grain precompute for web and marketing analytics.
#
# The sibling tables aggregate by dimension, so the person survives only as a `uniq` state. The
# credit side of attribution walks each converting person's touchpoints in order and needs them
# individually, so this table keeps one row per session with `person_id` un-aggregated.
#
# Store `channel_type` already classified to avoid resolving it on every read.


TABLE_BASE_NAME = "web_sessions_dimensional_preaggregated"


def DISTRIBUTED_WEB_SESSIONS_TABLE() -> str:
    return TABLE_BASE_NAME
