# Table for storing lazy-precomputed web stats PATHS aggregates (path tile
# with bounce rate).
#
# One row per (team, job, UTC hour, breakdown_value) where breakdown_value is
# the URL path (optionally prepended with host). For each session, we emit one
# row per pathname it touched. The bounce aggregate is set only when the
# pathname matched the session's entry pathname, which avgState ignores via
# NULL on other rows — that matches the v2 PATH_BOUNCE_QUERY semantic of
# attributing bounce to sessions that entered on the path.


TABLE_BASE_NAME = "web_stats_paths_preaggregated"


def DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME
