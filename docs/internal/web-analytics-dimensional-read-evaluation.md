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
A filter key counts as covered when the dimensional tables store its column, or can compute it
from stored columns.
The stored columns are declared in the dimensional table schemas
(`posthog/clickhouse/preaggregation/web_stats_dimensional_preaggregated_sql.py` and
`web_bounces_dimensional_preaggregated_sql.py`) and filled by the dimensional precompute insert
in `products/web_analytics/backend/hogql_queries/web_dimensional_precompute.py`, which maps each
event and session entry key to its column, for example `$entry_referring_domain` to
`referring_domain`.
`$channel_type` has no column of its own; it is computed at read time from stored columns such
as the referring domain, UTM, and click id columns, so it counts as covered by computation.
Do not read this set from
`products/web_analytics/backend/hogql_queries/pre_aggregated/properties.py`: that is the
deprecated v2 read path's mapping, and it differs.
It credits four keys the dimensional tables do not store (see the first of the three findings
below) and keys the referring domain as `$referring_domain`, not `$entry_referring_domain`.

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
The latency win is smaller than that cap, but the one-off tail alone does not bound it.

A dimensional read speeds up a filtered view only when that view serves live today, and two
groups serve live.
The first is the eligible one-off tail, near 1.8% of views: filter sets seen once, which
repeat too rarely for the hourly demand warmer or the lazy path to build a bucket.
About 59% of filtered views instead sit in a filter set seen five or more times, so the warmer
and the lazy path already serve that eligible repeat traffic.

The second group is larger, and repetition does not rescue it.
The lazy precompute gate rejects any filter that is not an event or person filter, and the
demand warmer takes the same gate, so a session-filtered view never receives a bucket however
often it repeats.
Many session keys still map to a stored column, including the seven entry-attribution keys in
the table below.
A view filtered on them serves live on every repeat, and a dimensional read could serve it.

The doc's own shares bound that second group from below.
Session filters appear on 33.6% of filtered views, and 80.0% of filtered views have every key
mapped to a dimensional column.
So at least 13.6% of filtered views are both fully covered and session-filtered, and stay live
however often they repeat.
That is about 1.4% of all views, and it is a floor: the exact accelerable share needs the
intersection of coverage and eligibility, which this measurement did not compute.

The operator column matters less than it looks.
A stored dimension is a plain column, so `icontains` and `is_not` filter it as well as
`exact` does.
The bound is set by key coverage, not by operator.

## Why filtered reads fall to the live path

The dimensional tables are not the reason.
The lazy precompute gate refuses any filter whose type is not `event` or `person`
(`check_common_eligibility` in
`products/web_analytics/backend/hogql_queries/web_lazy_precompute_common.py`).

| Filter type that keeps a view off lazy precompute  | Share of filtered views |
| -------------------------------------------------- | ----------------------- |
| None. Only event and person filters                | 65.0%                   |
| One or more session entry attribution filters      | 29.9%                   |
| Other session filters (duration, bounce, pathname) | 3.7%                    |
| A cohort filter                                    | 0.9%                    |

This table classifies filtered views by filter type only.
The filter-type check is one of the gate's checks, alongside team enrollment
(`is_precompute_enabled_for_team`), timezone, conversion goal, sampling, sessions join mode,
property access rules, and the 90 day range cap, plus per-runner checks for bounce rate,
scroll depth, breakdown, and order by.
A read also serves live on a freshness miss or when the team sits at its shape ceiling.
This measurement reads the URL filter set, so it sees none of those.
So the 65.0% row means the filter type does not block the view, not that the view is eligible,
and these shares rank filter types, not the full set of reasons a view serves live.

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
   It addresses 29.9% of filtered views, the largest filter-type reason they fall to the live
   path. The measurement does not rank the other gate checks, so this is the largest
   filter-type share, not the overall largest cause.
   The open question is population parity: a rewritten filter must select the same sessions
   as the live fallback, or the precomputed bucket answers a different question.
