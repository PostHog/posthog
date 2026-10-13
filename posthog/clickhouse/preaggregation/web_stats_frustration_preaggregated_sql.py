# Table for storing lazy-precomputed web stats FRUSTRATION metrics
# (rage clicks, dead clicks, exceptions).
#
# One row per (team, job, UTC hour, breakdown_value). The strategy that drives
# the frustration tile groups events per session × breakdown_value, then sums
# the per-session counts across sessions. Each session is attributed to its
# `min(session.$start_timestamp)` hour; rows from the same hour for the same
# breakdown_value are summed via `sumMerge` at read time.
#
# `breakdown_value` is whatever the runner's `_counts_breakdown_value()` emits
# (typically the URL pathname for the only breakdown the frustration tile ships
# today). The choice of `breakdown_by` is encoded into the INSERT AST and
# therefore into the lazy_computation cache key — different `breakdown_by`
# values become distinct precompute jobs, so storing the discriminator in the
# row is unnecessary.


TABLE_BASE_NAME = "web_stats_frustration_preaggregated"


def DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME
