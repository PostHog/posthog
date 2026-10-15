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
are empty in which groups), not counts.

```sql
SELECT
  lower(trim(toString(properties.searchQuery))) AS q,
  properties.groupType AS group_type,
  count() AS empties
FROM events
WHERE event = 'taxonomic filter empty result'
  AND timestamp >= now() - INTERVAL 90 DAY
GROUP BY q, group_type
ORDER BY empties DESC
LIMIT 40
```

### 4. Selection rate and dwell distribution

```sql
SELECT
  round(100 * countIf(toBool(properties.hadSelection)) / count(), 1) AS selection_rate_pct,
  quantile(0.5)(toFloat(properties.dwellMs)) AS p50_dwell_ms,
  quantile(0.9)(toFloat(properties.dwellMs)) AS p90_dwell_ms
FROM events
WHERE event = 'taxonomic filter closed'
  AND timestamp >= now() - INTERVAL 90 DAY
```

### 5. Selection-source mix

The buckets overlap. Write back relative shares only.

```sql
SELECT
  round(100 * countIf(toBool(properties.hadSearchInput)) / count(), 1) AS had_search_pct,
  round(100 * countIf(NOT toBool(properties.hadSearchInput) AND NOT toBool(properties.wasFromRecents) AND NOT toBool(properties.wasFromPinnedList)) / count(), 1) AS browsed_no_search_pct,
  round(100 * countIf(toBool(properties.wasFromRecents)) / count(), 1) AS from_recents_pct,
  round(100 * countIf(toBool(properties.wasFromPinnedList)) / count(), 1) AS from_pinned_pct
FROM events
WHERE event = 'taxonomic filter item selected'
  AND timestamp >= now() - INTERVAL 90 DAY
```

### 6. Position distribution

```sql
WITH positions AS (
  SELECT toInt(properties.position) AS pos
  FROM events
  WHERE event = 'taxonomic filter item selected'
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

Splits sessions into opens at `taxonomic filter add filter clicked`, then
compares opens with and without a category pick. This is approximate:
opens that don't emit the click are merged into the previous one.
Drives failure mode 1 in [failure-modes](failure-modes.md).

```sql
WITH opens AS (
  SELECT
    $session_id AS sid,
    arraySplit(
      (e, i) -> e = 'taxonomic filter add filter clicked' AND i > 1,
      groupArray(event),
      arrayEnumerate(groupArray(event))
    ) AS chunks
  FROM (
    SELECT $session_id, event, timestamp
    FROM events
    WHERE event IN ('taxonomic filter add filter clicked', 'taxonomic filter category selected',
                    'taxonomic filter empty result', 'taxonomic filter item selected')
      AND timestamp >= now() - INTERVAL 7 DAY
      AND $session_id IS NOT NULL
    ORDER BY timestamp
  )
  GROUP BY sid
),
per_open AS (
  SELECT
    has(chunk, 'taxonomic filter category selected') AS picked_category,
    has(chunk, 'taxonomic filter empty result') AS had_empty,
    has(chunk, 'taxonomic filter item selected') AS had_selection,
    indexOf(chunk, 'taxonomic filter category selected') AS cat_idx,
    indexOf(chunk, 'taxonomic filter empty result') AS empty_idx
  FROM opens
  ARRAY JOIN chunks AS chunk
)
SELECT
  round(100 * countIf(picked_category) / count(), 1) AS opens_with_category_pct,
  round(100 * countIf(had_empty AND picked_category) / countIf(picked_category), 1) AS empty_rate_after_category_pct,
  round(100 * countIf(had_empty AND NOT picked_category) / countIf(NOT picked_category), 1) AS empty_rate_without_category_pct,
  round(countIf(picked_category AND had_empty AND cat_idx < empty_idx) / countIf(picked_category AND had_empty AND empty_idx < cat_idx), 1) AS category_then_empty_ratio,
  round(100 * countIf(had_selection AND picked_category) / countIf(picked_category), 1) AS selection_after_category_pct,
  round(100 * countIf(had_selection AND NOT picked_category) / countIf(NOT picked_category), 1) AS selection_without_category_pct
FROM per_open
```

### 9. Search latency by group

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

The denominator is typed searches, which only the legacy surface emits,
while failures also fire on initial loads. Rates above 100 per 100
searches mean the group fails before anyone types. Read it as a ranking.

```sql
WITH f AS (
  SELECT toString(properties.groupType) AS g, count() AS n
  FROM events
  WHERE event = 'taxonomic filter fetch failed'
    AND timestamp >= now() - INTERVAL 7 DAY
  GROUP BY g
),
s AS (
  SELECT toString(properties.groupType) AS g, count() AS n
  FROM events
  WHERE event = 'taxonomic_filter_search_query'
    AND timestamp >= now() - INTERVAL 7 DAY
  GROUP BY g
)
SELECT
  f.g AS group_type,
  round(100 * f.n / sum(f.n) OVER (), 1) AS share_of_failures_pct,
  round(100 * f.n / nullIf(s.n, 0), 2) AS failures_per_100_searches
FROM f
LEFT JOIN s ON f.g = s.g
ORDER BY share_of_failures_pct DESC
LIMIT 15
```

### 11. Assistive feature funnels

Event match: answered, then suggested, then selected. Intent banner:
switch suggested, then switched. Write back the step ratios.

```sql
SELECT
  round(100 * countIf(event = 'taxonomic filter event match suggested')
    / countIf(event = 'taxonomic filter event match answered'), 1) AS match_suggested_per_answer_pct,
  round(100 * countIf(event = 'taxonomic filter event match selected')
    / countIf(event = 'taxonomic filter event match suggested'), 1) AS match_selected_per_suggestion_pct,
  round(100 * countIf(event = 'taxonomic filter search intent switched')
    / countIf(event = 'taxonomic filter search intent predicted' AND toString(properties.suggestsSwitch) = 'true'), 1) AS switched_per_switch_suggestion_pct
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
SELECT round(100 * countIf(recovered) / count(), 1) AS recovered_within_30s_pct
FROM (
  SELECT e.person_id, e.t, max(p.t > e.t AND p.t <= e.t + INTERVAL 30 SECOND) AS recovered
  FROM empties e
  LEFT JOIN picks p ON e.person_id = p.person_id
  GROUP BY e.person_id, e.t
)
```

## Updating the doc

1. Run each query via the PostHog MCP `execute-sql` against project 2 on
   us.posthog.com.
2. Convert results to ratios. Drop absolute event and user counts.
3. Update [product-reality](product-reality.md) and the five-line
   picture in `SKILL.md`, and bump the "last refreshed" date.
4. If the story changed, not just the numbers, revise the prose and
   check [failure-modes](failure-modes.md) and
   [feature-inventory](feature-inventory.md) still hold.
