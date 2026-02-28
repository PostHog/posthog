# Lazy precomputation for product analytics queries

Research into expanding automatic lazy precomputation to trends, funnels, and retention.

## Current state

The existing system precomputes `uniqExact(person_id)` grouped by `toStartOfDay(timestamp)`
for `$pageview` events. It uses `AggregateFunction(uniqExact, UUID)` which is _exact_
but expensive in both storage and merge cost.

## Proposed: switch to `uniq` (HyperLogLog) for automatic mode

`uniqExact` stores the full set of values; `uniq` uses a HyperLogLog sketch (~15KB per state)
with <2% error. For the automatic precomputation mode — where we prioritize speed over precision —
this is the right trade-off.

Benefits:

- ~100x smaller state size per group
- Much faster merge operations
- States are composable: `uniqMerge` across hourly buckets gives the same result
  as `uniq` over the full period
- Enables hourly bucketing (more granular reuse) without blowing up storage

## New generalized preaggregation table

The existing table has a single `uniq_exact_state AggregateFunction(uniqExact, UUID)` column.
For trends we need to support multiple aggregation types (count, uniq, sum, avg, min, max).
A generalized table stores different aggregate state columns:

```sql
CREATE TABLE preaggregation_v2 (
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY,

    -- Dimensions
    event String,
    breakdown_value Array(String),

    -- Aggregate states (only populated columns matter; unused are empty/zero)
    count_state AggregateFunction(sum, UInt64),         -- for count()
    uniq_state AggregateFunction(uniq, UUID),            -- for unique users (approx)
    sum_state AggregateFunction(sum, Float64),           -- for sum(property)
    min_state AggregateFunction(min, Float64),           -- for min(property)
    max_state AggregateFunction(max, Float64),           -- for max(property)
) ENGINE = AggregatingMergeTree()
PARTITION BY toYYYYMM(time_window_start)
ORDER BY (team_id, job_id, event, time_window_start, breakdown_value)
TTL expires_at
```

Key changes from v1:

- `event` column — enables one precomputation job to cover multiple event types
- `uniq_state` uses `uniq` (HyperLogLog) instead of `uniqExact`
- Multiple aggregate state columns for different math types
- `count_state` uses `sum` state so hourly buckets can be merged into daily

## Strategy per query type

### Trends

Trends are the most natural fit. The core pattern is:

```sql
SELECT <aggregation>(field) FROM events WHERE event = X GROUP BY toStartOfInterval(timestamp)
```

**What we can precompute by event + hour:**

| Math type            | Precomputed column | Write-side                      | Read-side (merge)       |
| -------------------- | ------------------ | ------------------------------- | ----------------------- |
| `total` (count)      | `count_state`      | `sumState(1)`                   | `sumMerge(count_state)` |
| `dau` (unique users) | `uniq_state`       | `uniqState(person_id)`          | `uniqMerge(uniq_state)` |
| `unique_session`     | `uniq_state`       | `uniqState($session_id)`        | `uniqMerge(uniq_state)` |
| `sum`                | `sum_state`        | `sumState(toFloat64(property))` | `sumMerge(sum_state)`   |
| `min`                | `min_state`        | `minState(toFloat64(property))` | `minMerge(min_state)`   |
| `max`                | `max_state`        | `maxState(toFloat64(property))` | `maxMerge(max_state)`   |

**What we cannot easily precompute:**

- `avg` — needs sum + count, can reconstruct from `sumMerge / sumMerge(count)`
- `median`, `p90`, `p95`, `p99` — quantiles are not mergeable across buckets
  (but `quantileState` exists in ClickHouse and IS mergeable)
- `weekly_active`, `monthly_active` — sliding windows, but can be computed from
  daily `uniq` states by merging the appropriate days
- `first_time_for_user` — inherently requires global knowledge

**Hourly bucketing enables flexible interval rollup:**

```sql
-- Hourly precomputed, but user wants daily view:
SELECT sumMerge(count_state)
FROM preaggregation_v2
WHERE event = '$pageview' AND job_id IN (...)
GROUP BY toStartOfDay(time_window_start)

-- Weekly:
GROUP BY toStartOfWeek(time_window_start)
```

### Retention

Retention asks: "Of users who did event A in period X, how many did event B in period Y?"

The current query runs entirely in one pass per actor:

1. Collect `groupUniqArrayIf(toStartOfDay(timestamp), start_event_expr)` per actor
2. Collect `groupUniqArrayIf(toStartOfDay(timestamp), return_event_expr)` per actor
3. Compute cohort assignments and return intervals with array operations
4. Final `count(DISTINCT actor_id)` grouped by `(cohort_period, return_interval)`

**Pre-aggregation opportunity: per-period user sets**

Instead of scanning all events, precompute which users did each event in each period:

```sql
-- Pre-aggregate: for each (event, period), store the set of users
INSERT INTO preaggregation_v2
SELECT
    toStartOfDay(timestamp) AS time_window_start,
    event,
    [] AS breakdown_value,
    sumState(toUInt64(1)) AS count_state,
    uniqState(person_id) AS uniq_state,
    ...
FROM events
WHERE event IN ('$pageview', 'purchase')
  AND timestamp >= {time_window_min}
  AND timestamp < {time_window_max}
GROUP BY time_window_start, event
```

Then the retention query can read from the precomputed table to get approximate
unique user counts per day. For the intersection (users who did A on day X AND B on day Y),
we cannot directly compute this from separate HLL sketches.

**However**, for an approximate mode we could:

1. **Relaxed retention**: Report `uniqMerge` of return-event users per period
   (ignoring whether they're the _same_ users as the start cohort).
   This gives "how many users did B in period Y" which is useful as an upper bound.

2. **Hourly-bucketed user arrays**: Store actual user ID arrays per (event, hour)
   for smaller teams, then compute intersections. But this doesn't scale.

3. **Theta sketches** (future): ClickHouse's `uniqTheta` supports set intersection
   via `bitmapAndCardinality`. This would enable:

   ```sql
   -- Users who did $pageview on day 0 AND purchase on day 3
   bitmapAndCardinality(
       uniqThetaMerge(day0_pageview_sketch),
       uniqThetaMerge(day3_purchase_sketch)
   )
   ```

**Recommendation**: Theta sketches are the right path for approximate retention.
They support union, intersection, and difference with ~2% error.
This is a real pre-aggregation win because the sketches are much smaller than the raw events
and enable arbitrary cohort/period intersection queries.

### Funnels

Funnels require per-user event sequences with strict ordering and conversion windows.
The current implementation:

1. Scans events matching any funnel step
2. Groups by `aggregation_target` (person_id)
3. Sorts events by timestamp per user
4. Passes to a UDF (`aggregate_funnel`) that checks step ordering and conversion windows
5. Counts users per step reached

**Why funnels are hardest to precompute:**

- Step ordering is per-user and depends on the specific sequence of events
- Conversion windows (e.g., "complete all steps within 14 days") require timestamp precision
- Exclusions depend on event order between specific steps
- The UDF operates on the full per-user event array

**Approximate funnel strategies:**

1. **Hourly step-user buckets (relaxed ordering)**:
   For each (event, hour), store which users triggered it.
   Then, for a funnel A -> B -> C:
   - Step 1: users who did A in any hour of the period
   - Step 2: users who did A in hour X AND B in hour Y where Y >= X
   - Step 3: users who did A, B, C in order (hour-level granularity)

   This relaxes ordering from _within-hour_ to _between-hours_.
   For a 14-day funnel window, hour-level ordering is usually sufficient.

   ```sql
   -- Precompute: for each (event, hour), store user set
   INSERT INTO funnel_preaggregation
   SELECT
       toStartOfHour(timestamp) AS time_window_start,
       event,
       uniqState(person_id) AS user_set
   FROM events
   WHERE event IN ('signup', 'onboarding_complete', 'first_purchase')
   GROUP BY time_window_start, event
   ```

   At query time, use `uniqTheta` intersections across ordered hour buckets.

2. **Per-user step timestamps (partial precomputation)**:
   Precompute per-user: "what's the earliest timestamp of each event type?"

   ```sql
   SELECT
       person_id,
       event,
       min(timestamp) AS first_occurrence,
       max(timestamp) AS last_occurrence,
       count() AS occurrence_count
   FROM events
   WHERE event IN (funnel_step_events)
   GROUP BY person_id, event
   ```

   This is a materialized view pattern. The funnel logic then only needs to check
   ordering on the precomputed min timestamps rather than scanning all events.

3. **Pre-filtered event stream**:
   The cheapest win: precompute just the event scan with step matching.
   The inner event query filters events to only those matching funnel steps,
   then the UDF processes them. We could cache this filtered scan:

   ```sql
   -- Store: (person_id, timestamp, step_matched) tuples
   -- This reduces the scan width dramatically for subsequent funnel variations
   -- that use the same events but different conversion windows or orderings
   ```

**Recommendation**: Strategy 2 (per-user step timestamps) gives the best trade-off.
It's exact for "ordered" funnels where we only need the first occurrence of each step,
and it reduces the data volume dramatically. For strict funnels (no intervening events),
we'd still need the full event stream.

## Implementation priority

1. **Trends** — highest value, lowest complexity.
   Most trends are count or unique-user aggregations grouped by time interval.
   Hourly precomputation with `uniqState`/`sumState` covers the majority of cases.

2. **Retention with theta sketches** — high value, medium complexity.
   Requires adding `uniqTheta` support but enables efficient cohort intersections.

3. **Funnels per-user step timestamps** — medium value, high complexity.
   Most useful for large teams with many repeated funnel queries on the same events.
