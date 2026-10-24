# Table for storing lazy-precomputed web stats table aggregates
#
# Stores per-hour, per-team, per-breakdown aggregate states for the two metrics
# surfaced by WebStatsTableQueryRunner's simple breakdowns: unique users and
# total pageviews. Reads merge across hourly buckets to answer arbitrary date
# ranges within the precomputed window.
#
# Shared by every low-cardinality simple breakdown and the channel-type
# breakdown — the `breakdown_by` column (a WebStatsBreakdown enum value) is the
# discriminator. Buckets are UTC hourly on the session's start timestamp, so the
# read matches the raw query's session-start attribution.


TABLE_BASE_NAME = "web_stats_preaggregated"


def DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME
