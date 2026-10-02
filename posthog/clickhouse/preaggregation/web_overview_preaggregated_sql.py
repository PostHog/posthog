# Table for storing lazy-precomputed web overview aggregates
#
# Stores per-hour, per-team aggregate states for the five metrics surfaced by
# WebOverviewQueryRunner: unique users, unique sessions, total pageviews,
# average session duration, average bounce rate. Reads merge across hourly
# buckets to answer arbitrary date ranges within the precomputed window.
#
# Buckets are UTC hourly so reads stay correct for any whole-hour-offset team
# timezone without storing per-team-tz data.


TABLE_BASE_NAME = "web_overview_preaggregated"


def DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME
