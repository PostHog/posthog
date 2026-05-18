# Refreshing the Product reality section

Re-run these every ~3 months. **Public OSS repo: convert to ratios before
writing back — never commit absolute event or user counts.** All queries
use a 90-day window; keep that consistent so trends are comparable.

### 1. Selection breakdown by source group type

Computes share of all `taxonomic filter item selected` events grouped
by `sourceGroupType`. Drives the "What users select" table.

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

Computes the share of each top-N search term among the top 8 only.
Avoids exposing absolute search volume.

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

Reveals taxonomy gaps. Use the qualitative findings (which terms are empty
in which groups), not absolute counts.

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

Drives the "About one in three opens results in a selection" line, plus
the dwell-time bullet.

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

Drives the "65% involve search / 19% browsed / 16% from recents / <1%
from pinned" line. Use only the relative shares — drop the absolute counts
before writing back.

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

Drives the "first three rows carry ~80% of selections" line.

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

Drives the "~93% typed / ~7% pasted" line.

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

## Updating the doc

1. Run each query above via `posthog:execute-sql` against
   project 2 on us.posthog.com.
2. Convert findings into ratios (drop absolute event and user counts).
3. Update the tables in `SKILL.md` and bump the "last refreshed" date.
4. If the qualitative story changed (e.g. `email` is no longer dominant,
   or pinned-items usage grew significantly), revise the prose above the
   tables — not just the numbers. Big changes deserve a heads-up to whoever
   owns the component, since they may affect ongoing roadmap decisions.
