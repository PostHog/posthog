# HogQL Queries for Web Analytics

This document explains how web analytics queries work in PostHog and how to view and test them.

## Viewing Query Examples

The best way to see what HogQL queries are generated for web analytics is to look at the snapshot tests:

**File:** `posthog/hogql_queries/web_analytics/test/test_sample_web_analytics_queries.py`

This test file contains comprehensive examples of all web analytics query types:

- Web overview queries (with and without filters)
- Web trends queries (unique users, page views, sessions over time)
- All 24 breakdown types (Page, InitialPage, DeviceType, Country, etc.)
- Event property filters (e.g., filtering by pathname)
- Session property filters (e.g., filtering by channel type)

### Regenerating Snapshots

To regenerate the HogQL query snapshots:

```bash
pytest posthog/hogql_queries/web_analytics/test/test_sample_web_analytics_queries.py --snapshot-update
```

The snapshots are stored in:
`posthog/hogql_queries/web_analytics/test/__snapshots__/test_sample_web_analytics_queries.hogql.ambr`

## Testing Queries with the API

You can test web analytics queries directly using PostHog's `/query` API endpoint.

**Resources:**

- [PostHog Query API Documentation](https://posthog.com/docs/api/query)
- [API Schema (Swagger UI)](https://app.posthog.com/api/schema/swagger-ui)

### 1. Create a Personal Access Token

1. Go to your PostHog instance → Settings → Personal API Keys (`/project/<project_id>/settings/user-api-keys`)
2. Click "Create personal API key"
3. Give it a name and select the appropriate scopes (At least 'Query: Read' is required)
4. Copy the token

### 2. Query the API

#### Example: Web Overview Query

```bash
curl -X POST https://app.posthog.com/api/projects/:project_id/query \
  -H "Authorization: Bearer PERSONAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "kind": "WebOverviewQuery",
      "dateRange": {
        "date_from": "2025-10-01",
        "date_to": "2025-10-31"
      },
      "properties": []
    }
  }'
```

#### Example: Web Stats Table Query with Breakdown

```bash
curl -X POST https://app.posthog.com/api/projects/:project_id/query \
  -H "Authorization: Bearer PERSONAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "kind": "WebStatsTableQuery",
      "dateRange": {
        "date_from": "2025-10-01",
        "date_to": "2025-10-31"
      },
      "breakdownBy": "Page",
      "limit": 10,
      "properties": []
    }
  }'
```

#### Example: With Event Property Filter

```bash
curl -X POST https://app.posthog.com/api/projects/:project_id/query \
  -H "Authorization: Bearer PERSONAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "kind": "WebStatsTableQuery",
      "dateRange": {
        "date_from": "2025-10-01",
        "date_to": "2025-10-31"
      },
      "breakdownBy": "Page",
      "limit": 10,
      "properties": [
        {
          "key": "$pathname",
          "operator": "exact",
          "value": "/pricing"
        }
      ]
    }
  }'
```

#### Example: Web Trends Query (Unique Users Over Time)

This query powers the "Unique visitors" trend line in the web analytics graphs tab:

```bash
curl -X POST https://app.posthog.com/api/projects/:project_id/query \
  -H "Authorization: Bearer PERSONAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "kind": "TrendsQuery",
      "dateRange": {
        "date_from": "2025-10-01",
        "date_to": "2025-10-31"
      },
      "interval": "day",
      "series": [
        {
          "event": "$pageview",
          "kind": "EventsNode",
          "math": "dau",
          "name": "Pageview",
          "custom_name": "Unique visitors"
        }
      ],
      "trendsFilter": {
        "display": "ActionsLineGraph"
      },
      "filterTestAccounts": true
    }
  }'
```

**Other trend query variations:**

- **Page views**: Use `"math": "total"` instead of `"dau"` for total pageview count
- **Sessions**: Use `"math": "unique_session"` for unique session count

### 3. Using Raw HogQL Queries from Snapshots

The examples above use high-level query types like `WebOverviewQuery` and `WebStatsTableQuery`. You can also use the **raw HogQL/SQL** queries directly from the snapshot files. This gives you full control and allows for customization.

#### Finding HogQL Queries in Snapshots

1. Open the snapshot file:

   ```bash
   posthog/hogql_queries/web_analytics/test/__snapshots__/test_sample_web_analytics_queries.hogql.ambr
   ```

2. Find the query you want. Each snapshot is named like:

   ```bash
   # name: TestSampleWebAnalyticsQueries.test_web_stats_breakdown_page
   ```

3. Copy the HogQL query between the triple quotes `'''`

#### Using HogQLQuery with the API

Use the `HogQLQuery` kind instead of web analytics-specific kinds:

```bash
curl -s -X POST https://app.posthog.com/api/projects/:project_id/query \
  -H "Authorization: Bearer PERSONAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "query": {
    "kind": "HogQLQuery",
    "query": "SELECT uniq(session_person_id) AS unique_users, sum(filtered_pageview_count) AS total_filtered_pageview_count FROM (SELECT any(events.person_id) AS session_person_id, session.session_id AS session_id, countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count FROM events WHERE and(notEquals(events.$session_id, NULL), or(equals(event, '$pageview'), equals(event, '$screen')), and(greaterOrEquals(timestamp, toDateTime('2025-10-01 00:00:00')), lessOrEquals(timestamp, toDateTime('2025-10-31 23:59:59')))) GROUP BY session_id) LIMIT 50000"
  }
}
EOF
```

#### Testing in the SQL Editor

The easiest way to test and modify HogQL queries:

1. Navigate to **PostHog → Data Management → SQL Editor** (or `/project/:project_id/hogql`)
2. Paste the HogQL query from the snapshot file
3. Click "Run query"
4. Modify the query as needed

The SQL editor uses `HogQLQuery` under the hood, so what works there will work in the API.

#### Complete Working Example

Here's a full example using a query from the snapshots:

**1. Query from snapshot** (`test_web_overview_query_snapshot`):

```sql
SELECT uniq(session_person_id) AS unique_users,
       sum(filtered_pageview_count) AS total_views,
       uniq(session_id) AS unique_sessions
FROM (
  SELECT any(events.person_id) AS session_person_id,
         session.session_id AS session_id,
         countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count
  FROM events
  WHERE and(
    notEquals(events.$session_id, NULL),
    or(equals(event, '$pageview'), equals(event, '$screen')),
    and(
      greaterOrEquals(timestamp, toDateTime('2025-10-01 00:00:00')),
      lessOrEquals(timestamp, toDateTime('2025-10-31 23:59:59'))
    )
  )
  GROUP BY session_id
)
LIMIT 50000
```

**2. API request:**

```bash
curl -X POST https://app.posthog.com/api/projects/123/query \
  -H "Authorization: Bearer PERSONAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "query": {
    "kind": "HogQLQuery",
    "query": "SELECT uniq(session_person_id) AS unique_users, sum(filtered_pageview_count) AS total_views, uniq(session_id) AS unique_sessions FROM (SELECT any(events.person_id) AS session_person_id, session.session_id AS session_id, countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count FROM events WHERE and(notEquals(events.$session_id, NULL), or(equals(event, '$pageview'), equals(event, '$screen')), and(greaterOrEquals(timestamp, toDateTime('2025-10-01 00:00:00')), lessOrEquals(timestamp, toDateTime('2025-10-31 23:59:59')))) GROUP BY session_id) LIMIT 50000"
  }
}
EOF
```

**3. Expected response:**

```json
{
  "results": [[12345, 45678, 23456]],
  "columns": ["unique_users", "total_views", "unique_sessions"],
  "types": ["UInt64", "UInt64", "UInt64"],
  "hogql": "SELECT ...",
  "timings": [...]
}
```

#### Modifying Queries for Your Needs

Common modifications you can make to the HogQL queries:

**Change date ranges:**

```sql
-- Replace these lines in WHERE clause:
greaterOrEquals(timestamp, toDateTime('2025-10-01 00:00:00')),
lessOrEquals(timestamp, toDateTime('2025-10-31 23:59:59'))

-- With your desired dates:
greaterOrEquals(timestamp, toDateTime('2025-11-01 00:00:00')),
lessOrEquals(timestamp, toDateTime('2025-11-30 23:59:59'))
```

**Add filters:**

```sql
-- Add to WHERE clause:
WHERE and(
  notEquals(events.$session_id, NULL),
  or(equals(event, '$pageview'), equals(event, '$screen')),
  -- Add your filters here:
  equals(properties.$pathname, '/pricing'),
  equals(session.$channel_type, 'Paid Search')
)
```

**Change aggregations:**

```sql
-- Add columns to SELECT:
SELECT uniq(session_person_id) AS unique_users,
       sum(filtered_pageview_count) AS total_views,
       avg(session_duration) AS avg_duration,  -- Added
       max(session_duration) AS max_duration   -- Added
```

**Adjust LIMIT:**

```sql
-- Change at the end of query:
LIMIT 100  -- Instead of 50000
```

#### Tips for Using Raw HogQL

**Query Performance:**

- **IMPORTANT**: Use specific date ranges to reduce data scanned, OLAP databases like ClickHouse can be resource-intensive and will fetch large amounts of data if not constrained to timestamp or other fields in the sorting key.
- Try to include the sorting key fields (`timestamp`, `event`, etc.) in your WHERE clause for better performance.
- Consider using `async=true` for long-running queries:

  ```json
  {
    "query": { ... },
    "async": true,
    "client_query_id": "my-custom-query-123"
  }
  ```

**Tracking Queries:**

- Use `client_query_id` to track your queries in PostHog's query log
- Check query performance in PostHog → Settings → System → Query Log

**Response Structure:**

- `results`: Array of result rows
- `columns`: Column names matching SELECT clause
- `types`: ClickHouse type for each column
- `hogql`: The executed HogQL query (useful for debugging)
- `timings`: Query execution breakdown

**Common Pitfalls:**

- Don't forget to escape quotes when embedding in JSON
- Date/time values must use `toDateTime()` function
- Session joins are automatic via `session.*` - don't add explicit JOINs
- Use `equals()` function instead of `=` operator in HogQL

### Query Schema

The query types and their schemas are defined in TypeScript:
`frontend/src/queries/schema/schema-general.ts`

These are automatically converted to Python Pydantic models in:
`posthog/schema.py`

**Note:** For raw HogQL queries, use the `HogQLQuery` kind instead of web analytics-specific kinds (`WebOverviewQuery`, `WebStatsTableQuery`). See the [HogQL documentation](https://posthog.com/docs/hogql) for complete query syntax reference.

## Query Structure Patterns

Web analytics queries typically follow a two-level structure:

## Key Concepts

### Session Properties vs Event Properties

Web analytics heavily uses **session properties** instead of person properties:

- **Session properties:** `session.$entry_pathname`, `session.$channel_type`, `session.$is_bounce`
- **Event properties:** `events.properties.$pathname`, `events.properties.$browser`

### Period Comparison

When comparing periods, queries use `*If` functions with timestamp conditions:

```sql
-- Current period
uniqIf(person_id, and(
  greaterOrEquals(start_timestamp, toDateTime('2025-10-01 00:00:00')),
  lessOrEquals(start_timestamp, toDateTime('2025-10-31 23:59:59'))
)) AS current_users

-- Previous period
uniqIf(person_id, and(
  greaterOrEquals(start_timestamp, toDateTime('2023-12-01 00:00:00')),
  lessOrEquals(start_timestamp, toDateTime('2023-12-31 23:59:59'))
)) AS previous_users
```

The inner query fetches events from both periods using `or(current_period, previous_period)`.

### Bounce Rate

**Important:** When showing bounce rate per page:

- Counts (visitors/views) use `events.properties.$pathname` (the page being viewed)
- Bounce rate uses `session.$entry_pathname` (the page where the session started)

This means "bounce rate for /pricing" shows bounces from sessions that **started** on /pricing.

## Available Breakdown Fields

Different breakdown types use different fields:
Refer to `posthog/schema.py` → `WebStatsBreakdown` for an up-to-date list.

| Breakdown Type                   | Field                                  | Type    |
| -------------------------------- | -------------------------------------- | ------- |
| `Page`                           | `events.properties.$pathname`          | Event   |
| `InitialPage`                    | `session.$entry_pathname`              | Session |
| `ExitPage`                       | `session.$end_pathname`                | Session |
| `PreviousPage`                   | `events.properties.$prev_pathname`     | Event   |
| `ScreenName`                     | `events.properties.$screen_name`       | Event   |
| `ExitClick`                      | `session.$exit_click_target`           | Session |
| `InitialReferringDomain`         | `session.$entry_referring_domain`      | Session |
| `InitialUTMSource`               | `session.$entry_utm_source`            | Session |
| `InitialUTMMedium`               | `session.$entry_utm_medium`            | Session |
| `InitialUTMCampaign`             | `session.$entry_utm_campaign`          | Session |
| `InitialUTMContent`              | `session.$entry_utm_content`           | Session |
| `InitialUTMTerm`                 | `session.$entry_utm_term`              | Session |
| `InitialUTMSourceMediumCampaign` | (combined field)                       | Session |
| `InitialChannelType`             | `session.$channel_type`                | Session |
| `Browser`                        | `properties.$browser`                  | Event   |
| `OS`                             | `properties.$os`                       | Event   |
| `DeviceType`                     | `properties.$device_type`              | Event   |
| `Viewport`                       | `properties.$viewport_width`           | Event   |
| `Country`                        | `properties.$geoip_country_code`       | Event   |
| `Region`                         | `properties.$geoip_subdivision_1_code` | Event   |
| `City`                           | `properties.$geoip_city_name`          | Event   |
| `Language`                       | `properties.$browser_language`         | Event   |
| `Timezone`                       | `properties.$timezone`                 | Event   |
| `FrustrationMetrics`             | (computed)                             | Session |

## Common Query Patterns

### Filtering by Date Range

```sql
WHERE and(
  greaterOrEquals(timestamp, toDateTime('2025-10-01 00:00:00')),
  lessOrEquals(timestamp, toDateTime('2025-10-31 23:59:59'))
)
```

### Event Type Filter (Pageviews and Screens)

```sql
WHERE or(equals(event, '$pageview'), equals(event, '$screen'))
```

## Debugging Queries in Tests

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

## More Resources

- [Web Analytics Contributing Guide](./contributing.md) - Frontend architecture and development workflow
- [HogQL History](https://posthog.slack.com/archives/C0351B1DMUY/p1754326078444019) - Marius and Eric explain the origins of HogQL
- [HogQL Python Handbook](https://posthog.com/handbook/engineering/databases/hogql-python) - Internal documentation
