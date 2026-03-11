# Query patterns

## HogQL queries

HogQL is PostHog's SQL dialect that runs on ClickHouse.
Endpoint queries use the `HogQLQuery` kind.

### Basic structure

```json
{
  "kind": "HogQLQuery",
  "query": "SELECT count() AS total FROM events WHERE event = '$pageview'"
}
```

### Common HogQL patterns for endpoints

#### Count events by day

```sql
SELECT
    count() AS total,
    toStartOfDay(timestamp) AS day
FROM events
WHERE event = '$pageview'
GROUP BY day
ORDER BY day DESC
LIMIT 30
```

#### Unique users by week

```sql
SELECT
    count(DISTINCT distinct_id) AS unique_users,
    toStartOfWeek(timestamp) AS week
FROM events
WHERE event = '$pageview'
GROUP BY week
ORDER BY week DESC
```

#### Event counts with property filter

```sql
SELECT
    count() AS total,
    properties.$browser AS browser
FROM events
WHERE event = '$pageview'
GROUP BY browser
ORDER BY total DESC
LIMIT 20
```

#### Using JSONExtractString for nested properties

```sql
SELECT
    count() AS total,
    JSONExtractString(properties, '$os') AS os
FROM events
WHERE event = '$pageview'
GROUP BY os
ORDER BY total DESC
```

#### Funnel-style sequential query

```sql
SELECT
    count(DISTINCT step1.distinct_id) AS step1_users,
    count(DISTINCT step2.distinct_id) AS step2_users
FROM events AS step1
LEFT JOIN events AS step2
    ON step1.distinct_id = step2.distinct_id
    AND step2.event = '$autocapture'
    AND step2.timestamp > step1.timestamp
    AND step2.timestamp < step1.timestamp + INTERVAL 1 DAY
WHERE step1.event = '$pageview'
```

### Variables in HogQL

Variables use `{variables.code_name}` placeholder syntax.

```json
{
  "kind": "HogQLQuery",
  "query": "SELECT count() AS total FROM events WHERE event = {variables.event_name}",
  "variables": {
    "<uuid>": {
      "variableId": "<uuid>",
      "code_name": "event_name",
      "value": "$pageview"
    }
  }
}
```

#### Variable with date function wrapping

```sql
SELECT count() AS total
FROM events
WHERE timestamp >= toDate({variables.start_date})
  AND timestamp < toDate({variables.end_date})
```

When materialized, the wrapper functions (`toDate`) are preserved
and applied to the variable value at query time.

#### Multiple variables

```sql
SELECT count() AS total, toStartOfDay(timestamp) AS day
FROM events
WHERE event = {variables.event_name}
  AND properties.$browser = {variables.browser}
GROUP BY day
```

### Variable constraints for materialization

Variables **can** be materialized when:

- Used in a `WHERE` clause with supported operators: `=`, `>=`, `>`, `<`, `<=`, `LIKE`, `ILIKE`, `NOT LIKE`, `NOT ILIKE`
- Each variable is in a simple comparison (not in OR conditions)
- Variables are NOT in a HAVING clause

Variables **cannot** be materialized when:

- Used in OR conditions
- Used in HAVING clause
- Used outside WHERE clause
- The operator is not in the supported set

### What happens during materialization

The query is transformed:

1. Variable WHERE clauses are **removed**
2. Variable columns are **added to SELECT** (aliased by code_name)
3. Variable columns are **added to GROUP BY** (deduplicated)

```text
Before:  SELECT count() FROM events WHERE event = {variables.event_name} GROUP BY day
After:   SELECT count(), event AS event_name FROM events GROUP BY day, event
```

At execution time, the materialized table is filtered:

```sql
SELECT * FROM materialized_table WHERE event_name = '$pageview'
```

## Insight queries

Insight queries use PostHog's structured query format.

### TrendsQuery

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "math": "total"
    }
  ],
  "interval": "day",
  "dateRange": {
    "date_from": "-7d",
    "date_to": null
  }
}
```

### TrendsQuery with breakdown

```json
{
  "kind": "TrendsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview",
      "math": "total"
    }
  ],
  "interval": "day",
  "breakdownFilter": {
    "breakdowns": [
      {
        "property": "$browser",
        "type": "event"
      }
    ]
  }
}
```

### FunnelsQuery

```json
{
  "kind": "FunnelsQuery",
  "series": [
    {
      "kind": "EventsNode",
      "event": "$pageview"
    },
    {
      "kind": "EventsNode",
      "event": "$autocapture"
    }
  ],
  "dateRange": {
    "date_from": "-30d"
  },
  "funnelsFilter": {
    "funnelWindowInterval": 14,
    "funnelWindowIntervalUnit": "day"
  }
}
```

### FunnelsQuery with breakdown

```json
{
  "kind": "FunnelsQuery",
  "series": [
    { "kind": "EventsNode", "event": "$pageview" },
    { "kind": "EventsNode", "event": "$autocapture" }
  ],
  "breakdownFilter": {
    "breakdowns": [{ "property": "$browser", "type": "event" }]
  }
}
```

Note: When materialized, funnel breakdowns use `final_prop` column, not `breakdown_value`.

### RetentionQuery

```json
{
  "kind": "RetentionQuery",
  "retentionFilter": {
    "targetEntity": { "id": "$pageview", "type": "events" },
    "returningEntity": { "id": "$pageview", "type": "events" },
    "period": "Week",
    "totalIntervals": 8
  },
  "dateRange": {
    "date_from": "-8w"
  }
}
```

### Other materializable query types

- `LifecycleQuery`
- `PathsQuery`
- `StickinessQuery`

All support materialization but **not** breakdown filtering.

## Supported math types for series

- `"total"` — total count
- `"dau"` — daily active users
- `"weekly_active"` — weekly active users
- `"monthly_active"` — monthly active users
- `"unique_group"` — unique groups
- `"hogql"` — custom HogQL expression (requires `math_hogql` field)
