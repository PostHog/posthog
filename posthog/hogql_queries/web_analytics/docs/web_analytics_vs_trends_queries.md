# Web Analytics vs Trends: Query Comparison

This document explains the fundamental differences between Web Analytics queries and Trends queries,
and why they may return different values for seemingly similar metrics like page views and unique users.

## Executive Summary

| Aspect          | Web Analytics                               | Trends                                         |
| --------------- | ------------------------------------------- | ---------------------------------------------- |
| Data model      | Session-centric                             | Event-centric                                  |
| Grouping        | `GROUP BY session_id, breakdown` first      | Direct event aggregation                       |
| Person counting | `any(person_id)` per session, then `uniq()` | `count(DISTINCT person_id)`                    |
| Session join    | Always joins with sessions table            | No session join (unless `unique_session` math) |
| Event types     | Hard-coded to `$pageview` + `$screen`       | Any event specified in series                  |

## Query Architecture

### Web Analytics: Session-First Aggregation

Web Analytics queries use a **two-level aggregation** pattern:

1. **Inner query**: Group by `(session_id, breakdown_value)` to get per-session metrics
2. **Outer query**: Aggregate across sessions using `uniq()`, `sum()`, etc.

### Trends: Direct Event Aggregation

Trends queries use **single-level aggregation** directly on events:

1. Filter events by type and date range
2. Apply aggregation function (`count()`, `count(DISTINCT person_id)`, etc.)

---

## Side-by-Side Query Comparison

### Counting Page Views

#### Web Analytics (WebStatsTable)

```sql
-- Outer query
SELECT
    breakdown_value AS "context.columns.breakdown_value",
    (
        sum(filtered_pageview_count) WHERE current_period,
        sum(filtered_pageview_count) WHERE previous_period
    ) AS "context.columns.views"
FROM (
    -- Inner query: GROUP BY session first
    SELECT
        any(person_id) AS filtered_person_id,
        count() AS filtered_pageview_count,  -- Pageviews per session per path
        {breakdown_value} AS breakdown_value,
        session.session_id AS session_id,
        min(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE
        (events.event = '$pageview' OR events.event = '$screen')
        AND {date_filter}
        AND {properties}
    GROUP BY session_id, breakdown_value  -- Key difference: session grouping
)
GROUP BY breakdown_value
```

#### Trends (TrendsQueryRunner)

```sql
SELECT
    count() AS total  -- Direct count of events
FROM events e
WHERE
    e.event = '$pageview'
    AND {date_filter}
    AND {properties}
-- No session grouping - each event counted directly
```

**Key Difference**: Web Analytics groups by session first, then sums. Trends counts events directly.
In practice, both should return the same total page views, but the intermediate representation differs.

---

### Counting Unique Users

#### Web Analytics (WebOverview)

```sql
SELECT
    uniqMerge(persons_uniq_state) AS visitors  -- Merge pre-aggregated unique states
FROM web_pre_aggregated_stats
WHERE {date_filter}

-- Or when using raw events:
SELECT
    uniq(filtered_person_id) AS visitors
FROM (
    SELECT
        any(person_id) AS filtered_person_id,  -- One person per session
        session.session_id AS session_id
    FROM events
    WHERE (events.event = '$pageview' OR events.event = '$screen')
    GROUP BY session_id  -- Dedupe within session first
)
```

#### Trends (DAU math)

```sql
SELECT
    count(DISTINCT e.person_id) AS total  -- Direct unique count
FROM events e
WHERE
    e.event = '$pageview'
    AND {date_filter}
```

**Key Difference**:

- Web Analytics: `any(person_id)` per session, then `uniq()` across sessions
- Trends: Direct `count(DISTINCT person_id)` on all events

Both should return the same unique user count in normal scenarios.

---

### Counting Sessions

#### Web Analytics (WebOverview)

```sql
SELECT
    uniq(session_id) AS sessions
FROM (
    SELECT
        session.session_id AS session_id
    FROM events
    WHERE (events.event = '$pageview' OR events.event = '$screen')
    GROUP BY session_id
)
```

#### Trends (unique_session math)

```sql
SELECT
    count(DISTINCT e."$session_id") AS total
FROM events e
WHERE
    e.event = '$pageview'
    AND {date_filter}
```

**Key Difference**: Similar approach, but Web Analytics joins with the sessions table
to access session properties like `$is_bounce`, `$entry_pathname`, etc.

---

## The Session Join Effect

### Web Analytics Inner Query Pattern

```sql
SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    {breakdown_value} AS breakdown_value,
    session.session_id AS session_id,
    any(session.$is_bounce) AS is_bounce,
    min(session.$start_timestamp) AS start_timestamp
FROM events
WHERE and(
    {inside_periods},
    {event_where},
    {all_properties},
    {where_breakdown}
)
GROUP BY session_id, breakdown_value
```

This pattern:

1. Joins each event with its session via `session.session_id`
2. Groups by `(session_id, breakdown_value)`
3. Uses `any(person_id)` to pick one person per session-breakdown combination
4. Counts pageviews per session per breakdown

### Why This Matters

When a session has multiple pageviews on the same path:

```text
Session A:
  - Event 1: /home (person_1)
  - Event 2: /home (person_1)
  - Event 3: /about (person_1)
```

**Web Analytics inner query produces:**

| session_id | breakdown_value | filtered_person_id | filtered_pageview_count |
| ---------- | --------------- | ------------------ | ----------------------- |
| A          | /home           | person_1           | 2                       |
| A          | /about          | person_1           | 1                       |

**Trends produces:**

| event     | person_id |
| --------- | --------- |
| $pageview | person_1  |
| $pageview | person_1  |
| $pageview | person_1  |

Both will correctly count 3 total pageviews, but the intermediate representation differs.

---

## Edge Case: Shared Session IDs

If two different users somehow share the same session_id (a bug scenario):

```text
Session X:
  - Event 1: /home (person_1)
  - Event 2: /home (person_2)  -- Different person, same session!
```

**Web Analytics**: `any(person_id)` picks one randomly, `uniq()` may count only 1 visitor
**Trends**: `count(DISTINCT person_id)` correctly counts 2 visitors

This is expected behavior - session IDs should be unique per user session.

---

## Pre-Aggregated Tables

Web Analytics can use pre-aggregated tables for performance:

```sql
SELECT
    sumMerge(pageviews_count_state) AS page_views,
    uniqMerge(persons_uniq_state) AS unique_users
FROM web_pre_aggregated_stats
WHERE
    team_id = {team_id}
    AND period_bucket >= {date_from}
    AND period_bucket <= {date_to}
```

These tables store ClickHouse aggregation states (`*State` columns) that can be merged
at query time using `*Merge` functions. This provides significant performance benefits
for large date ranges.

Trends queries always use the raw events table with direct aggregation.

---

## Timezone Considerations

### Web Analytics with Pre-Aggregated Tables

Pre-aggregated tables store data in **UTC buckets**. When querying:

```python
# Pre-aggregated tables require UTC
if self.used_preaggregated_tables:
    modifiers.convertToProjectTimezone = False
```

### Trends

Trends can convert timestamps to the team's timezone:

```sql
SELECT
    toStartOfDay(toTimeZone(e.timestamp, 'America/New_York')) AS day_start,
    count() AS total
FROM events e
GROUP BY day_start
```

This can cause the same event to appear in different day buckets depending on the query type.

---

## Test Coverage

See `posthog/hogql_queries/web_analytics/test/test_web_analytics_vs_trends_comparison.py` for:

- Functional tests comparing results from both systems
- Parameterized tests across various scenarios
- Edge case tests (shared session IDs)
- Snapshot tests capturing actual SQL queries

---

## Summary

| Scenario                | Web Analytics             | Trends                        | Match? |
| ----------------------- | ------------------------- | ----------------------------- | ------ |
| Simple pageview count   | Sum of per-session counts | Direct count                  | Yes    |
| Unique users            | `any()` then `uniq()`     | `count(DISTINCT)`             | Yes\*  |
| Sessions                | `uniq(session_id)`        | `count(DISTINCT $session_id)` | Yes    |
| Shared session_id (bug) | May undercount            | Correct count                 | No     |
| Non-pageview events     | Not supported             | Supported                     | N/A    |

\*Both match in normal scenarios; may differ with corrupted session data.
