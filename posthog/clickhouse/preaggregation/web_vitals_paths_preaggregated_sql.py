# Table for storing lazy-precomputed web vitals path-breakdown quantiles
#
# Stores per-day, per-team, per-path quantile-state aggregates matching
# `WebVitalsPathBreakdownQueryRunner`'s output. Reads merge across daily
# buckets and pick a single percentile (p75/p90/p99) via array indexing.
#
# Buckets are keyed by `toStartOfDay(event.timestamp, team_tz)` — the start
# of the team-local day (no session join in the raw query, so no session pad
# on the INSERT). One state column per Web Vitals metric (INP/LCP/CLS/FCP)
# — keeps the INSERT a single GROUP BY (vs. a discriminator column that
# would need ARRAY JOIN to fan out one event into four rows) and lets each
# metric tab read just one column.


TABLE_BASE_NAME = "web_vitals_paths_preaggregated"


def DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME
