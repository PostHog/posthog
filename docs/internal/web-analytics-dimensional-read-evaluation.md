# Serving filtered web analytics reads from the dimensional tables: evaluation

Decision: **no**. Do not add a read path over `web_stats_dimensional_preaggregated` and
`web_bounces_dimensional_preaggregated` to serve filtered dashboard reads.

This page records the measurement behind that answer, so nobody has to derive it again.
It answers [#92926](https://github.com/PostHog/posthog/issues/92926).
For the serving ladder itself, see [web-analytics-query-serving.md](web-analytics-query-serving.md).

## The question

Every distinct filter set mints its own lazy precompute namespace, capped per team by
`WEB_ANALYTICS_PRECOMPUTE_MAX_SHAPES_PER_TEAM` (`posthog/settings/web.py`).
The dimensional tables already store the fixed dimensions at full cardinality.
So a filtered read whose filters all sit on stored dimensions could read those tables
directly, with no per-shape bucket and no warming cost.

## Method

Web analytics keeps the filter set in the scene URL.
The measurement reads `$pageview` events on the web analytics scene over one fixed 14 day
window, extracts the `filters` URL parameter, and classifies each filter item by type, key,
and operator.
A filter key counts as covered when it maps to a stored column, using the same key-to-column
mapping the preaggregated read path applies in
`products/web_analytics/backend/hogql_queries/pre_aggregated/properties.py`.

Every figure below is a share of web analytics scene views in that one window.
Absolute volumes stay out of this page.

## The bound

| Slice of web analytics scene views            | Share of all views | Share of filtered views |
| --------------------------------------------- | ------------------ | ----------------------- |
| Carries a filter set                          | 10.6%              | 100%                    |
| Every filter key maps to a dimensional column | 8.5%               | 80.0%                   |
| ...and every operator is `exact`              | 7.7%               | 72.8%                   |
| Sits in a filter set seen once in the window  | 1.8%               | 16.9%                   |

The mean filtered view carries 1.37 filter items.

The first row bounds the idea at 8.5% of views.
The last row bounds the **latency** win much lower.
Most filtered views repeat.
About 59% of them sit in a filter set seen five or more times in the window, so the hourly
demand warmer already builds those buckets and the lazy path already serves them.
The slice a dimensional read would make faster is the one-off tail, near 1.8% of views.

The operator column matters less than it looks.
A stored dimension is a plain column, so `icontains` and `is_not` filter it as well as
`exact` does.
The bound is set by key coverage, not by operator.

## Why filtered reads fall to the live path

The dimensional tables are not the reason.
The lazy precompute gate refuses any filter whose type is not `event` or `person`
(`check_common_eligibility` in
`products/web_analytics/backend/hogql_queries/web_lazy_precompute_common.py`).

| Reason a filtered view misses lazy precompute      | Share of filtered views |
| -------------------------------------------------- | ----------------------- |
| None. It is eligible today (event and person only) | 65.0%                   |
| One or more session entry attribution filters      | 29.9%                   |
| Other session filters (duration, bounce, pathname) | 3.7%                    |
| A cohort filter                                    | 0.9%                    |

The 29.9% row uses only these seven keys: `$channel_type`, `$entry_referring_domain`, and
the five `$entry_utm_*` keys.
A rewrite for exactly those seven keys already exists.
`SESSION_PROPERTY_TO_FIRST_PAGEVIEW` in
`products/web_analytics/backend/hogql_queries/first_pageview_flag.py` maps each key to a
value recomputed from the session's first pageview.
The trends and calendar heatmap runners call that rewrite.
The lazy precompute gate does not, so it still sees a session filter and rejects the query.

That is the larger prize, and it needs no new read path.

## Three further findings against the idea

**It loses coverage against the tables it succeeds.**
The deprecated v2 preaggregated tables store `browser_version`, `os_version`, `country_name`,
and `time_zone`.
The dimensional tables have no column for any of them.
Views that v2 covers and the dimensional tables do not are 2.6% of filtered views.
The dimensional tables cover more elsewhere, mostly `$entry_referring_domain` and the viewport
dimensions, so the net key coverage gain is 6.9 points of filtered views.

**It is staler where staleness is least expected.**
`DIMENSIONAL_TTL_SECONDS` refreshes today hourly and the last two days daily, then holds
every older window for 90 days.
Lazy precompute refreshes those same older bands every 5 to 21 days.
So the dimensional job computes a 40 day old window once, and lazy precompute recomputes it.
Late arriving events and person merges reach one path and not the other.
Accepting that is a human call, not a measurement.

**Parity is only partly proven.**
`test_web_dimensional_precompute_parity.py` compares the device and geoip dimensions.
It does not compare `pathname`, `entry_pathname`, `end_pathname`, `referring_domain`, the
`utm_*` columns, the attribution flags, or the metadata columns.
Bounce geoip differs on purpose, because the dimensional path reads event geoip and v2 reads
the session's initial geoip.
A read path over these columns needs that gap closed first.

## What stays true

The write path keeps its purpose.
It is the precomputation framework successor to the v2 pre-aggregation ETL, and the scheduled
job runs for a small pilot audience, not the fleet.
The unread write cost today is bounded by that audience.
This decision rejects one use for the tables, not the tables.

## What to do instead

1. Close [#92926](https://github.com/PostHog/posthog/issues/92926) as not planned.
2. Evaluate wiring the first-pageview rewrite into the lazy precompute gate.
   It addresses 29.9% of filtered views, which is the largest single reason they serve live.
   The open question is population parity: a rewritten filter must select the same sessions
   as the live fallback, or the precomputed bucket answers a different question.
