# Refreshing product reality

Re-run these every ~3 months and update
[product-reality](product-reality.md). **Public OSS repo: convert to
ratios before writing back. Never commit absolute event or user counts.**

Queries 1 to 7 use a 90-day window; keep that consistent so trends are
comparable. Queries 8 to 12 use 7 days because they are heavier.

Exclude staff when the question is about customers, for example with the
project's test account filters.

### 1. Selection breakdown by source group type

Share of `taxonomic filter item selected` by `sourceGroupType`. Drives the
"What users select" table.

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

Share of each term among the top 8 only. Avoids exposing search volume.

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

Reveals scope mismatches. Write back the qualitative finding (which terms
are empty in which groups), not counts. The rebuild sends no `groupType`
for its `all`, `recent` and `pinned` scopes, so the query splits by
`surface`. Read an empty `group_type` on a `rebuild-menu` row as one of
those scopes, not as a group.

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

Measures engaged opens only. The legacy picker sends `taxonomic filter
closed` only after the user interacts, so untouched dismissals are
missing. The rebuild sends it on every close, so the query splits by
`surface`. Write back the `legacy-pill` row as the engaged-open rate.
`legacy-control` and empty values come only from older clients. Never pool the rebuild row with them.

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

The buckets overlap. Write back relative shares only. `from_recents_pct`
counts recents from any tab. `from_recents_in_suggested_pct` counts only
the Suggested tab, which backs the "Recents inside Suggested" row in
[feature-inventory](feature-inventory.md). The rebuild's merged `all`
scope has no `groupType`, so its recents fall outside that column.

```sql
SELECT
  round(100 * countIf(toBool(properties.hadSearchInput)) / count(), 1) AS had_search_pct,
  round(100 * countIf(NOT toBool(properties.hadSearchInput) AND NOT toBool(properties.wasFromRecents) AND NOT toBool(properties.wasFromPinnedList)) / count(), 1) AS browsed_no_search_pct,
  round(100 * countIf(toBool(properties.wasFromRecents)) / count(), 1) AS from_recents_pct,
  round(100 * countIf(toBool(properties.wasFromRecents) AND properties.groupType = 'suggested_filters') / count(), 1) AS from_recents_in_suggested_pct,
  round(100 * countIf(toBool(properties.wasFromPinnedList)) / count(), 1) AS from_pinned_pct
FROM events
WHERE event = 'taxonomic filter item selected'
  AND timestamp >= now() - INTERVAL 90 DAY
```

### 6. Position distribution

Legacy only. On the rebuild's merged `all` scope, `position` counts the
recents and pinned rows at the top, so it does not match legacy rows.

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

Splits each session after every legacy `taxonomic filter closed`, so
each chunk is close to one engaged legacy open. It is not exact: the
event fires when the logic unmounts, not when the picker visibly closes.
A picker that stays mounted (for example in `ColumnConfigurator.tsx`)
can put several picks in one chunk, and two mounted pickers can
interleave. Read the ratios as direction, not as exact rates. There is
no better open boundary in legacy telemetry today. Then it compares opens with and
without a category pick. Do not split on `taxonomic filter add filter
clicked`: it fires only when a property filter row is added, so most
opens have no start marker. The rebuild is left out, because its close
event fires on every close and its category event is different.
Suggested sends no `taxonomic filter empty result`, so the
without-category empty rate is too low. `category_then_empty_ratio` only
compares opens with a category pick, so it does not have this bias.
Drives failure mode 1 in [failure-modes](failure-modes.md).

```sql
WITH sessions AS (
  -- groupArray does not keep row order, so sort explicitly; on a timestamp tie the close sorts last
  SELECT
    $session_id AS sid,
    arrayMap(x -> tupleElement(x, 3), arraySort(groupArray((timestamp, event = 'taxonomic filter closed', event)))) AS steps
  FROM events
  WHERE event IN ('taxonomic filter closed', 'taxonomic filter category selected',
                  'taxonomic filter empty result', 'taxonomic filter item selected')
    -- the category event has no surface, and only legacy sends it
    AND (event = 'taxonomic filter category selected' OR coalesce(toString(properties.surface), '') != 'rebuild-menu')
    AND timestamp >= now() - INTERVAL 7 DAY
    AND $session_id IS NOT NULL
  GROUP BY sid
),
opens AS (
  -- split after each close, and drop the trailing chunk of an open that has not closed yet
  SELECT arrayFilter(
    c -> has(c, 'taxonomic filter closed'),
    arraySplit((e, prev) -> prev = 'taxonomic filter closed', steps, arrayPushFront(arrayPopBack(steps), ''))
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
    arrayLastIndex(x -> x = 'taxonomic filter empty result', chunk) AS last_empty_idx
  FROM opens
  ARRAY JOIN chunks AS chunk
)
SELECT
  round(100 * countIf(picked_category) / count(), 1) AS opens_with_category_pct,
  -- only an empty result after the category pick counts, not one the pick recovered from
  round(100 * countIf(picked_category AND last_empty_idx > cat_idx) / countIf(picked_category), 1) AS empty_rate_after_category_pct,
  round(100 * countIf(had_empty AND NOT picked_category) / countIf(NOT picked_category), 1) AS empty_rate_without_category_pct,
  round(countIf(picked_category AND had_empty AND cat_idx < empty_idx) / countIf(picked_category AND had_empty AND empty_idx < cat_idx), 1) AS category_then_empty_ratio,
  round(100 * countIf(had_selection AND picked_category) / countIf(picked_category), 1) AS selection_after_category_pct,
  round(100 * countIf(had_selection AND NOT picked_category) / countIf(NOT picked_category), 1) AS selection_without_category_pct
FROM per_open
```

### 9. Search latency by group

Legacy only. The rebuild does not send `taxonomic filter search latency`.

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

Only the legacy `infiniteListLogic` sends fetch failures, but both
surfaces send `taxonomic_filter_search_query`. Filter both sides to
`legacy-pill` so the rate does not fall as rebuild use grows. There is
no honest rate per group: a list also fails while it feeds Suggested,
and then the failure logs its own group but the search logs
`suggested_filters`. Rank groups by share of failures, and report one
overall rate. Failures also fire on initial loads, so the overall rate
is per typed search, not per request. The health dashboard divides by
timed searches instead, so its rate is higher.

```sql
WITH f AS (
  SELECT toString(properties.groupType) AS g, count() AS n
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
  round(100 * (SELECT sum(n) FROM f) / (SELECT n FROM s), 2) AS overall_failures_per_100_searches
FROM f
ORDER BY share_of_failures_pct DESC
LIMIT 15
```

### 11. Assistive feature funnels

Event match: answered, then suggested, then selected. Intent banner:
banner shown, then switched. Write back the step ratios.

- `event match suggested` carries no query or request ID, so no key
  counts suggestions exactly. The raw count is too high: a tab switch
  that reuses a cached answer sends it again. The distinct count per
  person, session and suggestion list is too low: two queries with the
  same list count once. The query returns both, and the true rate lies
  between them.
- Selections have no exposure ID to pair with a suggestion, so the
  selection step compares person-sessions on both sides.
- Every experiment arm sends `search intent predicted`, but only the
  `banner` arm can switch. On the banner arm, `shown` can be true when
  `suggestsSwitch` is false (it seems to lag one prediction), so the
  query needs both.

```sql
SELECT
  round(100 * uniqIf((person_id, $session_id, toString(properties.suggestedEvents)), event = 'taxonomic filter event match suggested')
    / countIf(event = 'taxonomic filter event match answered'), 1) AS match_suggested_per_answer_low_pct,
  round(100 * countIf(event = 'taxonomic filter event match suggested')
    / countIf(event = 'taxonomic filter event match answered'), 1) AS match_suggested_per_answer_high_pct,
  round(100 * uniqIf((person_id, $session_id), event = 'taxonomic filter event match selected')
    / uniqIf((person_id, $session_id), event = 'taxonomic filter event match suggested'), 1) AS sessions_selecting_per_session_suggested_pct,
  round(100 * countIf(event = 'taxonomic filter search intent switched')
    / countIf(event = 'taxonomic filter search intent predicted' AND properties.variant = 'banner'
              AND toString(properties.suggestsSwitch) = 'true' AND toString(properties.shown) = 'true'), 1) AS switched_per_shown_banner_pct
FROM events
WHERE event IN ('taxonomic filter event match answered', 'taxonomic filter event match suggested',
                'taxonomic filter event match selected', 'taxonomic filter search intent predicted',
                'taxonomic filter search intent switched')
  AND timestamp >= now() - INTERVAL 7 DAY
```

### 12. Recovery after an empty result

Share of empty results followed by a searched selection from the same
person within 30 seconds. This counts every empty result, including
repeats while typing, so it reads lower than the health dashboard's
recovery tile. Compare each against its own history, not each other.

```sql
WITH empties AS (
  SELECT person_id, timestamp AS t
  FROM events
  WHERE event = 'taxonomic filter empty result'
    AND timestamp >= now() - INTERVAL 7 DAY
),
picks AS (
  SELECT person_id, timestamp AS t
  FROM events
  WHERE event = 'taxonomic filter item selected'
    AND toBool(properties.hadSearchInput)
    AND timestamp >= now() - INTERVAL 7 DAY
)
-- ASOF matches only the next pick per empty result, so the join does not grow as empties x picks
SELECT round(100 * countIf(p.t > e.t AND p.t <= e.t + INTERVAL 30 SECOND) / count(), 1) AS recovered_within_30s_pct
FROM empties e
ASOF LEFT JOIN picks p ON e.person_id = p.person_id AND p.t > e.t
```

## Updating the doc

1. Run each query via the PostHog MCP `posthog:execute-sql` against project 2 on
   us.posthog.com.
2. Convert results to ratios. Drop absolute event and user counts.
3. Update [product-reality](product-reality.md) and the five-line
   picture in `SKILL.md`, and bump the "last refreshed" date.
4. If the story changed, not just the numbers, revise the prose and
   check [failure-modes](failure-modes.md) and
   [feature-inventory](feature-inventory.md) still hold.
