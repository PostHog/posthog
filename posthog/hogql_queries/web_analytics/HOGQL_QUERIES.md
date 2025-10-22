# HogQL Queries for Web Analytics

This document explains how to write HogQL queries to replicate the web analytics components in PostHog. All examples use the non-pre-aggregated query runners.

## Query Structure

Web analytics queries typically follow a two-level structure:

1. **Inner Query**: Groups by session and/or breakdown value, calculates session-level metrics
2. **Outer Query**: Aggregates across sessions to produce final results

### Key Concepts

- **Session Grouping**: Events are grouped by `session.session_id`
- **Period Comparison**: Uses `*If` functions with timestamp conditions to compare current vs previous period
- **Bounce Rate**: Calculated from `session.$is_bounce` field
- **Breakdown Values**: Different fields depending on the breakdown type (pathname, entry_pathname, etc.)

## Web Overview Query

The web overview provides high-level metrics about website traffic.

### Without Period Comparison

```sql
SELECT
  uniq(session_person_id) AS unique_users,
  NULL AS previous_unique_users,
  sum(filtered_pageview_count) AS total_filtered_pageview_count,
  NULL AS previous_total_filtered_pageview_count,
  uniq(session_id) AS unique_sessions,
  NULL AS previous_unique_sessions,
  avg(session_duration) AS avg_duration_s,
  NULL AS previous_avg_duration_s,
  avg(is_bounce) AS bounce_rate,
  NULL AS previous_bounce_rate
FROM (
  SELECT
    any(events.person_id) AS session_person_id,
    session.session_id AS session_id,
    min(session.$start_timestamp) AS start_timestamp,
    any(session.$session_duration) AS session_duration,
    countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count,
    any(session.$is_bounce) AS is_bounce
  FROM events
  WHERE and(
    notEquals(events.$session_id, NULL),
    or(equals(event, '$pageview'), equals(event, '$screen')),
    and(
      greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
      lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59'))
    )
  )
  GROUP BY session_id
  HAVING and(
    greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
    lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
  )
)
LIMIT 50000
```

### With Period Comparison

When comparing periods, the query uses conditional aggregations (`*If` functions):

```sql
SELECT
  uniqIf(session_person_id, and(
    greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
    lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
  )) AS unique_users,
  uniqIf(session_person_id, and(
    greaterOrEquals(start_timestamp, toDateTime('2023-12-01 00:00:00')),
    lessOrEquals(start_timestamp, toDateTime('2023-12-31 23:59:59'))
  )) AS previous_unique_users,
  sumIf(filtered_pageview_count, and(
    greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
    lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
  )) AS total_filtered_pageview_count,
  sumIf(filtered_pageview_count, and(
    greaterOrEquals(start_timestamp, toDateTime('2023-12-01 00:00:00')),
    lessOrEquals(start_timestamp, toDateTime('2023-12-31 23:59:59'))
  )) AS previous_total_filtered_pageview_count,
  -- ... similar for other metrics
FROM (
  -- Inner query fetches both periods
  SELECT
    any(events.person_id) AS session_person_id,
    session.session_id AS session_id,
    min(session.$start_timestamp) AS start_timestamp,
    any(session.$session_duration) AS session_duration,
    countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count,
    any(session.$is_bounce) AS is_bounce
  FROM events
  WHERE and(
    notEquals(events.$session_id, NULL),
    or(equals(event, '$pageview'), equals(event, '$screen')),
    or(
      -- Current period
      and(
        greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
        lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59'))
      ),
      -- Previous period
      and(
        greaterOrEquals(timestamp, toDateTime('2023-12-01 00:00:00')),
        lessOrEquals(timestamp, toDateTime('2023-12-31 23:59:59'))
      )
    )
  )
  GROUP BY session_id
  HAVING or(
    and(
      greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
      lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
    ),
    and(
      greaterOrEquals(start_timestamp, toDateTime('2023-12-01 00:00:00')),
      lessOrEquals(start_timestamp, toDateTime('2023-12-31 23:59:59'))
    )
  )
)
LIMIT 50000
```

**Key Points:**

- Inner query fetches events from both periods using `or(current_period, previous_period)`
- Outer query uses `*If` functions to split aggregations by period
- Results include both current and previous values for each metric

## Entry Paths Query

Shows which pages users first land on (uses `session.$entry_pathname`).

```sql
SELECT
  breakdown_value AS `context.columns.breakdown_value`,
  tuple(uniq(filtered_person_id), NULL) AS `context.columns.visitors`,
  tuple(sum(filtered_pageview_count), NULL) AS `context.columns.views`,
  divide(
    `context.columns.visitors`.1,
    sum(`context.columns.visitors`.1) OVER ()
  ) AS `context.columns.ui_fill_fraction`
FROM (
  SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    session.$entry_pathname AS breakdown_value,
    session.session_id AS session_id,
    any(session.$is_bounce) AS is_bounce,
    min(session.$start_timestamp) AS start_timestamp
  FROM events
  WHERE and(
    greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
    lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59')),
    or(equals(event, '$pageview'), equals(event, '$screen')),
    notEquals(breakdown_value, NULL)
  )
  GROUP BY session_id, breakdown_value
)
GROUP BY `context.columns.breakdown_value`
ORDER BY
  `context.columns.visitors` DESC,
  `context.columns.views` DESC,
  `context.columns.breakdown_value` ASC
LIMIT 50000
```

**Key Points:**

- Uses `session.$entry_pathname` as the breakdown value
- Groups by both `session_id` and `breakdown_value` in inner query
- Outer query aggregates by breakdown value
- Results show visitors and views per entry page

## Exit Paths Query

Shows which pages users exit from (uses `session.$end_pathname`).

```sql
SELECT
  breakdown_value AS `context.columns.breakdown_value`,
  tuple(uniq(filtered_person_id), NULL) AS `context.columns.visitors`,
  tuple(sum(filtered_pageview_count), NULL) AS `context.columns.views`,
  divide(
    `context.columns.visitors`.1,
    sum(`context.columns.visitors`.1) OVER ()
  ) AS `context.columns.ui_fill_fraction`
FROM (
  SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    session.$end_pathname AS breakdown_value,
    session.session_id AS session_id,
    any(session.$is_bounce) AS is_bounce,
    min(session.$start_timestamp) AS start_timestamp
  FROM events
  WHERE and(
    greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
    lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59')),
    or(equals(event, '$pageview'), equals(event, '$screen')),
    notEquals(breakdown_value, NULL)
  )
  GROUP BY session_id, breakdown_value
)
GROUP BY `context.columns.breakdown_value`
ORDER BY
  `context.columns.visitors` DESC,
  `context.columns.views` DESC,
  `context.columns.breakdown_value` ASC
LIMIT 50000
```

**Key Points:**

- Uses `session.$end_pathname` as the breakdown value
- Otherwise identical structure to entry paths query

## Paths Breakdown Query

Shows metrics for all pages visited (uses `events.properties.$pathname`).

### Simple Version (No Bounce Rate)

```sql
SELECT
  breakdown_value AS `context.columns.breakdown_value`,
  tuple(uniq(filtered_person_id), NULL) AS `context.columns.visitors`,
  tuple(sum(filtered_pageview_count), NULL) AS `context.columns.views`,
  divide(
    `context.columns.visitors`.1,
    sum(`context.columns.visitors`.1) OVER ()
  ) AS `context.columns.ui_fill_fraction`
FROM (
  SELECT
    any(person_id) AS filtered_person_id,
    count() AS filtered_pageview_count,
    events.properties.$pathname AS breakdown_value,
    session.session_id AS session_id,
    any(session.$is_bounce) AS is_bounce,
    min(session.$start_timestamp) AS start_timestamp
  FROM events
  WHERE and(
    greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
    lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59')),
    or(equals(event, '$pageview'), equals(event, '$screen')),
    notEquals(breakdown_value, NULL)
  )
  GROUP BY session_id, breakdown_value
)
GROUP BY `context.columns.breakdown_value`
ORDER BY
  `context.columns.visitors` DESC,
  `context.columns.views` DESC,
  `context.columns.breakdown_value` ASC
LIMIT 50000
```

### With Bounce Rate

When including bounce rate, the query uses a LEFT JOIN to combine counts with bounce rate data:

```sql
SELECT
  counts.breakdown_value AS `context.columns.breakdown_value`,
  tuple(counts.visitors, counts.previous_visitors) AS `context.columns.visitors`,
  tuple(counts.views, counts.previous_views) AS `context.columns.views`,
  tuple(bounce.bounce_rate, bounce.previous_bounce_rate) AS `context.columns.bounce_rate`,
  divide(
    `context.columns.visitors`.1,
    sum(`context.columns.visitors`.1) OVER ()
  ) AS `context.columns.ui_fill_fraction`
FROM (
  -- Counts subquery: visitors and views per pathname
  SELECT
    breakdown_value,
    uniqIf(filtered_person_id, and(
      greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
      lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
    )) AS visitors,
    uniqIf(filtered_person_id, false) AS previous_visitors,
    sumIf(filtered_pageview_count, and(
      greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
      lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
    )) AS views,
    sumIf(filtered_pageview_count, false) AS previous_views
  FROM (
    SELECT
      any(person_id) AS filtered_person_id,
      count() AS filtered_pageview_count,
      events.properties.$pathname AS breakdown_value,
      session.session_id AS session_id,
      min(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE and(
      or(equals(events.event, '$pageview'), equals(events.event, '$screen')),
      greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
      lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59')),
      notEquals(breakdown_value, NULL)
    )
    GROUP BY session_id, breakdown_value
  )
  GROUP BY breakdown_value
) AS counts
LEFT JOIN (
  -- Bounce rate subquery: uses $entry_pathname
  SELECT
    breakdown_value,
    avgIf(is_bounce, and(
      greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
      lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
    )) AS bounce_rate,
    avgIf(is_bounce, false) AS previous_bounce_rate
  FROM (
    SELECT
      session.$entry_pathname AS breakdown_value,
      any(session.$is_bounce) AS is_bounce,
      session.session_id AS session_id,
      min(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE and(
      or(equals(events.event, '$pageview'), equals(events.event, '$screen')),
      notEquals(breakdown_value, NULL),
      greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
      lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59'))
    )
    GROUP BY session_id, breakdown_value
  )
  GROUP BY breakdown_value
) AS bounce
ON equals(counts.breakdown_value, bounce.breakdown_value)
ORDER BY
  `context.columns.visitors` DESC,
  `context.columns.views` DESC,
  `context.columns.breakdown_value` ASC
LIMIT 50000
```

**Key Points:**

- Bounce rate uses `session.$entry_pathname` (the page where the session started)
- Main counts use `events.properties.$pathname` (the page being viewed)
- This distinction is important: bounce rate shows "bounces from sessions that started on this page"
- JOIN ensures bounce rate aligns with the pathname

## Common Patterns

### Filtering by Date Range

```sql
WHERE and(
  greaterOrEquals(timestamp, toDateTime('2024-01-01 00:00:00')),
  lessOrEquals(timestamp, toDateTime('2024-01-31 23:59:59'))
)
```

### Event Type Filter (Pageviews and Screens)

```sql
WHERE or(equals(event, '$pageview'), equals(event, '$screen'))
```

### Session-Level Aggregation

```sql
SELECT
  any(person_id) AS filtered_person_id,
  session.session_id AS session_id,
  min(session.$start_timestamp) AS start_timestamp,
  -- other metrics
FROM events
GROUP BY session_id
```

### Period Comparison Aggregation

```sql
uniqIf(person_id, and(
  greaterOrEquals(start_timestamp, toDateTime('2024-01-01 00:00:00')),
  lessOrEquals(start_timestamp, toDateTime('2024-01-31 23:59:59'))
)) AS current_period_users
```

### UI Fill Fraction (for visual bars)

```sql
divide(
  `context.columns.visitors`.1,
  sum(`context.columns.visitors`.1) OVER ()
) AS `context.columns.ui_fill_fraction`
```

This calculates what fraction of total visitors this row represents.

## Using These Queries in Tests

To print the HogQL syntax in tests instead of ClickHouse SQL:

```python
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext

# In your test
runner = WebOverviewQueryRunner(team=team, query=query)
query_ast = runner.to_query()

context = HogQLContext(
    team_id=team.pk,
    enable_select_queries=True,
)
hogql = print_ast(query_ast, context=context, dialect="hogql")
print(hogql)
```

## Available Breakdown Fields

Different breakdown types use different fields:

| Breakdown Type             | Field                             |
| -------------------------- | --------------------------------- |
| `PAGE`                     | `events.properties.$pathname`     |
| `INITIAL_PAGE`             | `session.$entry_pathname`         |
| `EXIT_PAGE`                | `session.$end_pathname`           |
| `SCREEN_NAME`              | `events.properties.$screen_name`  |
| `INITIAL_REFERRING_DOMAIN` | `session.$entry_referring_domain` |
| `INITIAL_UTM_SOURCE`       | `session.$entry_utm_source`       |
| `INITIAL_CHANNEL_TYPE`     | `session.$channel_type`           |
| `BROWSER`                  | `properties.$browser`             |
| `OS`                       | `properties.$os`                  |
| `DEVICE_TYPE`              | `properties.$device_type`         |
| `COUNTRY`                  | `properties.$geoip_country_code`  |

## Notes

- All timestamp comparisons use `toDateTime()` for proper type handling
- `NULL` checks use `notEquals(field, NULL)` instead of `isNotNull()`
- Tuples are used to return paired current/previous values
- Window functions (`OVER ()`) compute fractions across result set
- `ui_fill_fraction` provides data for visual bar charts in the UI
