# Refreshing product reality

Re-run these every ~3 months and update [product-reality](product-reality.md).
**Public OSS repo: convert to ratios before writing back.
Never commit absolute event or user counts.**

Queries 1 to 7 use a 90-day window; keep that consistent so trends are comparable.
Queries 8 to 12 use 7 days because they are heavier.
Queries 13 to 15 use 90 days.

Exclude staff when the question is about customers, for example with the project's test account filters.

## Contents

- [Live metrics](#live-metrics)
- [1. Selection breakdown by source group type](#1-selection-breakdown-by-source-group-type)
- [2. Top searches (share of top-N)](#2-top-searches-share-of-top-n)
- [3. Top empty-result searches](#3-top-empty-result-searches)
- [4. Selection rate and dwell distribution](#4-selection-rate-and-dwell-distribution)
- [5. Selection-source mix](#5-selection-source-mix)
- [6. Position distribution](#6-position-distribution)
- [7. Input mode mix](#7-input-mode-mix)
- [8. The category trap (open level)](#8-the-category-trap-open-level)
- [9. Search latency by group](#9-search-latency-by-group)
- [10. Fetch failures by group](#10-fetch-failures-by-group)
- [11. Assistive feature funnels](#11-assistive-feature-funnels)
- [12. Recovery after an empty result](#12-recovery-after-an-empty-result)
- [13. Tab use, docking and empty-result rate](#13-tab-use-docking-and-empty-result-rate)
- [14. Which tabs users open](#14-which-tabs-users-open)
- [15. Users who return to the same tab](#15-users-who-return-to-the-same-tab)
- [Updating the doc](#updating-the-doc)

## Live metrics

Nine of these queries are saved as metrics in the PostHog data catalog for project 2.
Run a metric with `posthog:data-catalog-metric-run` to get the current value instead of reading a figure from this skill.
The metrics are proposed until a person approves them in the data catalog, so treat their results as noncanonical until then.
The metric and the query here hold the same SQL.
When you change one, change the other in the same PR (`posthog:data-catalog-metric-update` for the metric).

The rebuilt menu is removed from the code, but its `rebuild-menu` events stay in the data until they age out of the query windows.
That is why these queries still split or filter by `surface`.
Once no window holds a `rebuild-menu` row, simplify a query and its metric together.

| Query | Metric                                               |
| ----- | ---------------------------------------------------- |
| 4     | `taxonomic_filter_engaged_selection_rate_by_surface` |
| 5     | `taxonomic_filter_selection_mix_legacy`              |
| 6     | `taxonomic_filter_row_position_share_legacy`         |
| 8     | `taxonomic_filter_category_trap`                     |
| 9     | `taxonomic_filter_search_latency_by_group`           |
| 10    | `taxonomic_filter_fetch_failures_by_group`           |
| 11    | `taxonomic_filter_assistive_funnels`                 |
| 12    | `taxonomic_filter_empty_result_recovery_by_surface`  |
| 13    | `taxonomic_filter_tab_use_legacy`                    |

### 1. Selection breakdown by source group type

Share of `taxonomic filter item selected` by `sourceGroupType`.
Drives the "What users select" table.

```sql
SELECT
  properties.sourceGroupType AS source_group_type,
  count() AS selections,
  round(100 * count() / (
    SELECT count()
    FROM events
    WHERE event = 'taxonomic filter item selected'
      AND timestamp >= now() - INTERVAL 90 DAY
  ), 1) AS share_pct
FROM events
WHERE event = 'taxonomic filter item selected'
  AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY source_group_type
ORDER BY selections DESC
LIMIT 30
```

### 2. Top searches (share of top-N)

Share of each term among the top 8 only.
Avoids exposing search volume.

```sql
WITH top_terms AS (
  SELECT lower(trim(toString(properties.searchQuery))) AS q, count() AS searches
  FROM events
  WHERE event = 'taxonomic_filter_search_query'
    AND timestamp >= now() - INTERVAL 90 DAY
    AND length(toString(properties.searchQuery)) > 0
  GROUP BY q
  ORDER BY searches DESC
  LIMIT 8
)
SELECT q, round(100 * searches / sum(searches) OVER (), 1) AS share_pct
FROM top_terms
ORDER BY share_pct DESC
```

### 3. Top empty-result searches

Reveals scope mismatches.
Write back the qualitative finding (which terms are empty in which groups), not counts.
The rebuild sends no `groupType` for its `all`, `recent` and `pinned` scopes, so the query splits by `surface`.
Read an empty `group_type` on a `rebuild-menu` row as one of those scopes, not as a group.

```sql
SELECT
  lower(trim(toString(properties.searchQuery))) AS q,
  properties.surface AS surface,
  properties.groupType AS group_type,
  count() AS empties
FROM events
WHERE event = 'taxonomic filter empty result'
  AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY q, surface, group_type
ORDER BY empties DESC
LIMIT 40
```

### 4. Selection rate and dwell distribution

Measures engaged opens only.
The legacy picker sends `taxonomic filter closed` only after the user interacts, so untouched dismissals are missing.
The rebuild sends it on every close, so the query splits by `surface`.
Write back the `legacy-pill` row as the engaged-open rate.
`legacy-control` and empty values come only from older clients.
Never pool the rebuild row with them.

```sql
SELECT
  properties.surface AS surface,
  round(100 * countIf(toBool(properties.hadSelection)) / count(), 1) AS selection_rate_pct,
  quantile(0.5)(toFloat(properties.dwellMs)) AS p50_dwell_ms,
  quantile(0.9)(toFloat(properties.dwellMs)) AS p90_dwell_ms
FROM events
WHERE event = 'taxonomic filter closed'
  AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY surface
ORDER BY surface
```

### 5. Selection-source mix

The buckets overlap.
Write back relative shares only.
`from_recents_pct` counts recents from any tab.
`from_recents_in_suggested_pct` counts only the Suggested tab, which backs the "Recents inside Suggested" row in [feature-inventory](feature-inventory.md).
`suggested_share_pct` backs the Suggested share, and `recents_share_of_suggested_pct` backs "about half of Suggested picks are recents".
The rebuild's `all`, `recent` and `pinned` scopes have no `groupType`, so the query is legacy only and every column shares one base.

```sql
SELECT
  round(100 * countIf(toBool(properties.hadSearchInput)) / count(), 1) AS had_search_pct,
  round(100 * countIf(NOT toBool(properties.hadSearchInput) AND NOT toBool(properties.wasFromRecents) AND NOT toBool(properties.wasFromPinnedList)) / count(), 1) AS browsed_no_search_pct,
  round(100 * countIf(toBool(properties.wasFromRecents)) / count(), 1) AS from_recents_pct,
  round(100 * countIf(toBool(properties.wasFromRecents) AND properties.groupType = 'suggested_filters') / count(), 1) AS from_recents_in_suggested_pct,
  round(100 * countIf(toBool(properties.wasFromPinnedList)) / count(), 1) AS from_pinned_pct,
  round(100 * countIf(properties.groupType = 'suggested_filters') / count(), 1) AS suggested_share_pct,
  round(100 * countIf(toBool(properties.wasFromRecents) AND properties.groupType = 'suggested_filters')
    / countIf(properties.groupType = 'suggested_filters'), 1) AS recents_share_of_suggested_pct
FROM events
WHERE event = 'taxonomic filter item selected'
  AND coalesce(toString(properties.surface), '') != 'rebuild-menu'
  AND timestamp >= now() - INTERVAL 90 DAY
```

### 6. Position distribution

Legacy only.
On the rebuild's merged `all` scope, `position` counts the recents and pinned rows at the top, so it does not match legacy rows.

```sql
WITH positions AS (
  SELECT toInt(properties.position) AS pos
  FROM events
  WHERE event = 'taxonomic filter item selected'
    AND coalesce(toString(properties.surface), '') != 'rebuild-menu'
    AND timestamp >= now() - INTERVAL 90 DAY
    AND properties.position IS NOT NULL
)
SELECT
  pos,
  round(100 * count() / (SELECT count() FROM positions), 1) AS share_pct
FROM positions
GROUP BY pos
ORDER BY pos ASC
LIMIT 10
```

### 7. Input mode mix

```sql
SELECT
  properties.inputMode AS input_mode,
  round(100 * count() / (
    SELECT count()
    FROM events
    WHERE event = 'taxonomic_filter_search_query'
      AND timestamp >= now() - INTERVAL 90 DAY
      AND properties.inputMode IS NOT NULL
  ), 1) AS share_pct
FROM events
WHERE event = 'taxonomic_filter_search_query'
  AND timestamp >= now() - INTERVAL 90 DAY
  AND properties.inputMode IS NOT NULL
GROUP BY input_mode
ORDER BY share_pct DESC
```

### 8. The category trap (open level)

Splits each session after every legacy `taxonomic filter closed`, so each chunk is close to one engaged legacy open.
It is not exact: the event fires when the logic unmounts, not when the picker visibly closes.
A picker that stays mounted (for example in `ColumnConfigurator.tsx`) can put several picks in one chunk, and two mounted pickers can interleave.
Read the ratios as direction, not as exact rates.
There is no better open boundary in legacy telemetry today.
Then it compares opens with and without a category pick.
Do not split on `taxonomic filter add filter clicked`: it fires only when a property filter row is added, so most opens have no start marker.
The rebuild is left out, because its close event fires on every close and its category event is different.
`taxonomic filter category selected` also fires when the user switches to Suggested, Recent or Pinned.
Those switches do not narrow search, so the query drops them, and "category pick" means a real group.
The query also drops any open that picked the SQL expression category: legacy commits a SQL expression without sending `taxonomic filter item selected`, so a success there would look like a failure.
An existing SQL expression filter reopens straight on that tab without a category event, so the query also drops any open whose close has `groupType = 'hogql_expression'`.
Legacy clients that predate All-tab measurement send no `taxonomic filter empty result` from Suggested, so their without-category empty rate is too low.
The same gap biases `category_then_empty_ratio` upward: an empty search on Suggested followed by a category pick never counts in its base.
New clients send `scope = 'all'` when the aggregate empty state is visible and `scope = 'category'` for remote category searches.
Compare windows with the same coverage, or filter both periods to `scope = 'category'` for a category-only comparison.
`selection_after_category_pct` and `selection_without_category_pct` do not use empty-result events, so they are the most reliable output of this query.
Drives failure mode 1 in [failure-modes](failure-modes.md).

```sql
WITH sessions AS (
  -- groupArray does not keep row order, so sort explicitly; on a timestamp tie the close sorts last
  SELECT
    $session_id AS sid,
    arrayMap(x -> tupleElement(x, 3), arraySort(groupArray((timestamp, event = 'taxonomic filter closed',
      -- mark SQL expression picks and closes so their opens can be dropped below
      multiIf(event = 'taxonomic filter category selected' AND toString(properties.groupType) = 'hogql_expression', 'sql expression category',
              event = 'taxonomic filter closed' AND toString(properties.groupType) = 'hogql_expression', 'taxonomic filter closed on sql expression',
              event))))) AS steps
  FROM events
  WHERE event IN ('taxonomic filter closed', 'taxonomic filter category selected',
                  'taxonomic filter empty result', 'taxonomic filter item selected')
    -- the category event has no surface, and only legacy sends it
    AND (event = 'taxonomic filter category selected' OR coalesce(toString(properties.surface), '') != 'rebuild-menu')
    -- a switch to a meta tab does not narrow search
    AND NOT (event = 'taxonomic filter category selected'
             AND toString(properties.groupType) IN ('suggested_filters', 'recent_filters', 'pinned_filters'))
    AND timestamp >= now() - INTERVAL 7 DAY
    AND $session_id IS NOT NULL
  GROUP BY sid
),
opens AS (
  -- split after each close, and drop the trailing chunk of an open that has not closed yet
  SELECT arrayFilter(
    -- has() needs an exact match, so chunks that close on SQL expression drop out here too
    c -> has(c, 'taxonomic filter closed') AND NOT has(c, 'sql expression category'),
    arraySplit((e, prev) -> startsWith(prev, 'taxonomic filter closed'), steps, arrayPushFront(arrayPopBack(steps), ''))
  ) AS chunks
  FROM sessions
),
per_open AS (
  SELECT
    has(chunk, 'taxonomic filter category selected') AS picked_category,
    has(chunk, 'taxonomic filter empty result') AS had_empty,
    has(chunk, 'taxonomic filter item selected') AS had_selection,
    indexOf(chunk, 'taxonomic filter category selected') AS cat_idx,
    indexOf(chunk, 'taxonomic filter empty result') AS empty_idx,
    arrayLastIndex(x -> x = 'taxonomic filter empty result', chunk) AS last_empty_idx,
    arrayLastIndex(x -> x = 'taxonomic filter item selected', chunk) AS last_sel_idx
  FROM opens
  ARRAY JOIN chunks AS chunk
)
SELECT
  round(100 * countIf(picked_category) / count(), 1) AS opens_with_category_pct,
  -- only an empty result after the category pick counts, not one the pick recovered from
  round(100 * countIf(picked_category AND last_empty_idx > cat_idx) / countIf(picked_category), 1) AS empty_rate_after_category_pct,
  round(100 * countIf(had_empty AND NOT picked_category) / countIf(NOT picked_category), 1) AS empty_rate_without_category_pct,
  round(countIf(picked_category AND had_empty AND cat_idx < empty_idx) / countIf(picked_category AND had_empty AND empty_idx < cat_idx), 1) AS category_then_empty_ratio,
  -- only a pick after the category pick counts
  round(100 * countIf(picked_category AND last_sel_idx > cat_idx) / countIf(picked_category), 1) AS selection_after_category_pct,
  round(100 * countIf(had_selection AND NOT picked_category) / countIf(NOT picked_category), 1) AS selection_without_category_pct
FROM per_open
```

### 9. Search latency by group

Legacy only.
The rebuild does not send `taxonomic filter search latency`.

```sql
SELECT
  toString(properties.groupType) AS group_type,
  round(quantile(0.5)(toFloat(properties.time_to_see_data_ms))) AS p50_ms,
  round(quantile(0.9)(toFloat(properties.time_to_see_data_ms))) AS p90_ms,
  round(quantile(0.99)(toFloat(properties.time_to_see_data_ms))) AS p99_ms
FROM events
WHERE event = 'taxonomic filter search latency'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY group_type
HAVING count() > 200
ORDER BY p90_ms DESC
LIMIT 15
```

### 10. Fetch failures by group

Both surfaces send fetch failures and `taxonomic_filter_search_query`, but the rebuild sends no `groupType` on its meta-scopes.
Filter both sides to `legacy-pill` so the per-group ranking stays clean and the rate does not move as rebuild use grows.
There is no honest rate per group: a list also fails while it feeds Suggested, and then the failure logs its own group but the search logs `suggested_filters`.
Rank groups by share of failures, and report one overall rate.
Failures also fire on the first load, when the query is empty, and no search event matches those.
So the overall rate counts only failures with a non-empty query.
It is failure events per search query event, not failed searches.
The failure event has no `inputMode`, so "search query" here covers typed and pasted input alike: on Suggested every list that feeds the tab can fail and send its own event for one search, and short queries that never reach a list still count in the base.
There is no request ID to count failed searches exactly.
The share ranking keeps first-load failures, because they show which groups fail.
The health dashboard divides by timed searches instead, so its rate is higher.

```sql
WITH f AS (
  SELECT
    toString(properties.groupType) AS g,
    count() AS n,
    countIf(length(trim(toString(properties.searchQuery))) > 0) AS nonempty_n
  FROM events
  WHERE event = 'taxonomic filter fetch failed'
    AND properties.surface = 'legacy-pill'
    AND timestamp >= now() - INTERVAL 7 DAY
  GROUP BY g
),
s AS (
  SELECT count() AS n
  FROM events
  WHERE event = 'taxonomic_filter_search_query'
    AND properties.surface = 'legacy-pill'
    AND timestamp >= now() - INTERVAL 7 DAY
)
SELECT
  f.g AS group_type,
  round(100 * f.n / sum(f.n) OVER (), 1) AS share_of_failures_pct,
  round(100 * (SELECT sum(nonempty_n) FROM f) / (SELECT n FROM s), 2) AS failure_events_per_100_search_queries
FROM f
ORDER BY share_of_failures_pct DESC
LIMIT 15
```

### 11. Assistive feature funnels

Intent banner: banner shown, then switched.
Write back the step ratios.

- Every experiment arm sends `search intent predicted`, but only the `banner` arm can switch.
  On the banner arm, `shown` can be true when `suggestsSwitch` is false (it seems to lag one prediction), so the query needs both.

```sql
SELECT
  round(100 * countIf(event = 'taxonomic filter search intent switched')
    / countIf(event = 'taxonomic filter search intent predicted' AND properties.variant = 'banner'
              AND toString(properties.suggestsSwitch) = 'true' AND toString(properties.shown) = 'true'), 1) AS switched_per_shown_banner_pct
FROM events
WHERE event IN ('taxonomic filter search intent predicted', 'taxonomic filter search intent switched')
  AND timestamp >= now() - INTERVAL 7 DAY
```

### 12. Recovery after an empty result

Share of empty results followed by a searched selection in the same person, session and surface within 30 seconds, per surface.
The surfaces cover different empty states, so never pool them.
Legacy clients that predate All-tab measurement send none from Suggested.
New clients mark All-tab empties with `scope = 'all'`; compare periods with the same coverage or restrict both to `scope = 'category'`.
Two pickers open at once in one session can still match each other; exact matching would need a picker instance ID.
This counts every empty result, including repeats while typing, so it reads lower than the health dashboard's recovery tile.
Compare each against its own history, not each other.

```sql
WITH empties AS (
  SELECT person_id, $session_id AS sid, coalesce(toString(properties.surface), '') AS surface, timestamp AS t
  FROM events
  WHERE event = 'taxonomic filter empty result'
    AND timestamp >= now() - INTERVAL 7 DAY
    AND $session_id IS NOT NULL
),
picks AS (
  SELECT person_id, $session_id AS sid, coalesce(toString(properties.surface), '') AS surface, timestamp AS t
  FROM events
  WHERE event = 'taxonomic filter item selected'
    AND toBool(properties.hadSearchInput)
    AND timestamp >= now() - INTERVAL 7 DAY
    AND $session_id IS NOT NULL
)
-- ASOF matches only the next pick per empty result, so the join does not grow as empties x picks
SELECT
  e.surface AS surface,
  round(100 * countIf(p.t > e.t AND p.t <= e.t + INTERVAL 30 SECOND) / count(), 1) AS recovered_within_30s_pct
FROM empties e
ASOF LEFT JOIN picks p ON e.person_id = p.person_id AND e.sid = p.sid AND e.surface = p.surface AND p.t > e.t
GROUP BY surface
ORDER BY surface
```

### 13. Tab use, docking and empty-result rate

Legacy closes over 90 days, plus the legacy empty-result rate.
Backs the person properties, standalone Recent and Pinned, docking and empty-result rows in [feature-inventory](feature-inventory.md).
Two caveats limit what this query can say:

- `groupType` on a close is the tab open at close, and `hadSelection` stays true once any pick happens.
  A pick on one tab followed by a switch to Person properties counts as a Person properties success, and the reverse is missed.
  So the per-tab rates are final-tab associations, not exact per-tab conversion.
- `categoryRailDocked` is the saved preference, not whether a rail showed.
  It stays on in single-group pickers, where `InfiniteSelectResults` hides the rail.
  So the docking columns describe the preference, not visible docking.

```sql
SELECT
  round(100 * countIf(toBool(properties.hadSelection)) / count(), 1) AS all_tabs_selection_pct,
  round(100 * countIf(toBool(properties.hadSelection) AND properties.groupType = 'person_properties')
    / countIf(properties.groupType = 'person_properties'), 1) AS person_properties_selection_pct,
  round(100 * countIf(properties.groupType = 'recent_filters') / count(), 2) AS closes_on_recent_tab_pct,
  round(100 * countIf(toBool(properties.hadSelection) AND properties.groupType = 'recent_filters')
    / countIf(properties.groupType = 'recent_filters'), 1) AS recent_tab_selection_pct,
  round(100 * countIf(properties.groupType = 'pinned_filters') / count(), 2) AS closes_on_pinned_tab_pct,
  round(100 * countIf(toBool(properties.categoryRailDocked)) / count(), 1) AS docked_closes_pct,
  round(100 * countIf(toBool(properties.hadSelection) AND toBool(properties.categoryRailDocked))
    / countIf(toBool(properties.categoryRailDocked)), 1) AS docked_selection_pct,
  round(100 * countIf(toBool(properties.hadSelection) AND NOT toBool(properties.categoryRailDocked))
    / countIf(NOT toBool(properties.categoryRailDocked)), 1) AS undocked_selection_pct,
  round(100 * (
    SELECT count() FROM events
    WHERE event = 'taxonomic filter empty result' AND properties.surface = 'legacy-pill'
      AND timestamp >= now() - INTERVAL 90 DAY
  ) / (
    SELECT count() FROM events
    WHERE event = 'taxonomic_filter_search_query' AND properties.surface = 'legacy-pill'
      AND timestamp >= now() - INTERVAL 90 DAY
  ), 1) AS empty_results_per_100_search_queries
FROM events
WHERE event = 'taxonomic filter closed'
  AND properties.surface = 'legacy-pill'
  AND timestamp >= now() - INTERVAL 90 DAY
```

### 14. Which tabs users open

Share of category clicks by tab, over 90 days.
It is a relative click mix, not an open rate: one open can switch tabs several times, and Suggested, Recent and Pinned clicks are in the base too.
It shows which tabs people click least, which backs the pseudo-category tabs row in [feature-inventory](feature-inventory.md) as a lead.
Before you remove a tab, measure distinct opens or users that use it over one window, as step 6 of "Before removing anything" asks.

```sql
SELECT
  toString(properties.groupType) AS group_type,
  round(100 * count() / sum(count()) OVER (), 1) AS share_of_category_clicks_pct
FROM events
WHERE event = 'taxonomic filter category selected'
  AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY group_type
ORDER BY share_of_category_clicks_pct DESC
LIMIT 30
```

### 15. Users who return to the same tab

Per-user return to a category tab over 90 days.
Backs the "reopen on the last category used" entry in [contested-decisions](contested-decisions.md).
Suggested, Recent and Pinned do not count as a category.
Category clicks carry no open ID, so "again" means on a later day.
Counting a later session instead raises the first rate by about three points.
The second rate divides by people who closed the legacy picker, so rebuild-only users are not in its base.

```sql
WITH tab_days AS (
  SELECT person_id, toString(properties.groupType) AS group_type, uniqExact(toDate(timestamp)) AS days
  FROM events
  WHERE event = 'taxonomic filter category selected'
    AND properties.groupType NOT IN ('suggested_filters', 'recent_filters', 'pinned_filters')
    AND timestamp >= now() - INTERVAL 90 DAY
  GROUP BY person_id, group_type
),
switchers AS (
  SELECT person_id, max(days) >= 2 AS returned
  FROM tab_days
  GROUP BY person_id
)
SELECT
  round(100 * countIf(returned) / count(), 1) AS switchers_returning_to_same_tab_pct,
  round(100 * countIf(returned) / (
    SELECT uniqExact(person_id) FROM events
    WHERE event = 'taxonomic filter closed' AND properties.surface = 'legacy-pill'
      AND timestamp >= now() - INTERVAL 90 DAY
  ), 1) AS legacy_picker_users_returning_pct
FROM switchers
```

## Updating the doc

1. Run each metric in the table above with `posthog:data-catalog-metric-run`, and the other queries via the PostHog MCP `posthog:execute-sql` against project 2 on us.posthog.com.
2. Convert results to ratios.
   Drop absolute event and user counts.
3. Update [product-reality](product-reality.md) and the five-line picture in `SKILL.md`, and bump the "last refreshed" date.
4. If the story changed, not just the numbers, revise the prose and check [failure-modes](failure-modes.md) and [feature-inventory](feature-inventory.md) still hold.
