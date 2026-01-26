---
name: posthog-query-data
description: 'Retrieve data from PostHog: system (insights, dashboards, cohorts, feature flags, experiments, surveys, groups, group type mappings, data warehouse tables, teams), analytics data captured with SDKs (events, properties, property values), and connected data warehouse.'
---

# Querying data in PostHog

Use the `posthog:execute-sql` MCP tool to execute HogQL queries. HogQL is PostHog's variant of SQL that supports most of ClickHouse SQL. We use terms "HogQL" and "SQL" interchangeably.

## Search types

Proactively use differnt search types depending on a task:

- Grep-like (regex search) with `match()`, `LIKE`, `ILIKE`, `position`, `multiMatch`, etc.
- Full-text search with `hasToken`, `hasTokenCaseInsensitive`, etc. Make sure you pass string constants to `hasToken*` functions.
- Dumping results to a file and using bash commands to process potentially large outputs.

## Data Groups

PostHog has two distinct groups of data you can query:

### 1. System Data (PostHog-Created Data)

Data created directly in PostHog by users - metadata about PostHog setup.

All system tables are prefixed with `system.`:

| Table                           | Description                                           |
| ------------------------------- | ----------------------------------------------------- |
| `system.actions`                | Named event combinations for filtering                |
| `system.cohorts`                | Groups of persons for segmentation                    |
| `system.dashboards`             | Collections of insights                               |
| `system.dashboard_tiles`        | Links insights to dashboards with layout              |
| `system.data_warehouse_sources` | Connected external data sources                       |
| `system.experiments`            | A/B tests and experiments                             |
| `system.exports`                | Export jobs                                           |
| `system.feature_flags`          | Feature flags for controlling rollouts                |
| `system.groups`                 | Group entities                                        |
| `system.group_type_mappings`    | Group type definitions                                |
| `system.ingestion_warnings`     | Data ingestion issues                                 |
| `system.insight_variables`      | Variables used in insights                            |
| `system.insights`               | Visual and textual representations of aggregated data |
| `system.notebooks`              | Collaborative documents with embedded insights        |
| `system.surveys`                | Questionnaires and feedback forms                     |
| `system.teams`                  | Team/project settings                                 |

**Example - List insights:**

```sql
SELECT id, name, short_id FROM system.insights WHERE NOT deleted LIMIT 10
```

#### System Models Reference

Schema reference for PostHog's core system models, organized by domain:

- [Actions](references/models-actions.md)
- [Cohorts & Persons](references/models-cohorts.md)
- [Dashboards, Tiles & Insights](references/models-dashboards-insights.md)
- [Flags & Experiments](references/models-flags-experiments.md)
- [Groups](references/models-groups.md)
- [Notebooks](references/models-notebooks.md)
- [Surveys](references/models-surveys.md)

#### Entity Relationships

| From       | Relation | To               | Join                                  |
| ---------- | -------- | ---------------- | ------------------------------------- |
| Dashboard  | M:N      | Insight          | via `dashboardtile`                   |
| Experiment | 1:1      | FeatureFlag      | `feature_flag_id`                     |
| Experiment | N:1      | Cohort           | `exposure_cohort_id`                  |
| Survey     | N:1      | FeatureFlag      | `linked_flag_id`, `targeting_flag_id` |
| Survey     | N:1      | Insight          | `linked_insight_id`                   |
| Group      | N:1      | GroupTypeMapping | `group_type_index` (logical)          |
| Cohort     | M:N      | Person           | via `cohortpeople`                    |
| Person     | 1:N      | PersonDistinctId | `person_id`                           |

All entities are scoped by a team by default. You cannot access data of another team unless you switch a team.

### 2. Captured Data (Analytics Data)

Data collected via the PostHog SDK - used for product analytics.

| Table                 | Description                                            |
| --------------------- | ------------------------------------------------------ |
| `events`              | Recorded events from SDKs                              |
| `persons`             | Individuals captured by the SDK. "Person" = "user"     |
| `groups`              | Groups of individuals (organizations, companies, etc.) |
| `sessions`            | Session data captured by the SDK                       |
| Data warehouse tables | Connected external data sources and custom views       |

**Key concepts:**

- **Events**: Standardized events/properties start with `$` (e.g., `$pageview`). Custom ones start with any other character.
- **Properties**: Key-value metadata accessed via `properties.foo.bar` or `properties.foo['bar']` for special characters
- **Person properties**: Access via `events.person.properties.foo` or `persons.properties.foo`
- **Unique users**: Use `events.person_id` for counting unique users

**Example - Weekly active users:**

```sql
SELECT toStartOfWeek(timestamp) AS week, count(DISTINCT person_id) AS users
FROM events
WHERE event = '$pageview'
  AND timestamp > now() - INTERVAL 8 WEEK
GROUP BY week
ORDER BY week DESC
```

## Querying guidelines

### Skipping index

You should use the skipping index signature to write optimized analytical queries.

### Time ranges

All analytical queries and subqueries must always have time ranges set for supported tables (events). If the user doesn't state it, Assume default time range based on the data volume, like a day, week, or month.

#### How you should use time ranges

<example>
User: Find events from returning browsers - browsers that appeared both yesterday and today
Assistant:
```sql
SELECT event FROM events WHERE timestamp >= now() - INTERVAL 1 DAY and properties['$browser'] IN (SELECT properties['$browser'] FROM events WHERE timestamp >= now() - INTERVAL 2 DAY and timestamp < now() - INTERVAL 1 DAY)
```
</example>

#### How you should NOT write queries

<example>
User: List 10 events with SQL
Assistant:
```sql
SELECT event, timestamp, distinct_id, properties FROM events ORDER BY timestamp DESC LIMIT 10
```
</example>

### JOINs

#### General guidelines

Keep in mind that the right expression is loaded in memory when joining data in ClickHouse, so the joining query or table must always fit in memory. Common strategies:

- Analytical functions and combinators.
- Subqueries as a source or filter.
- Arrays (arrayMap, arrayJoin) and ARRAY JOIN.

#### System data

You are allowed joining system data. Insights are the most used entity, so keep it on the left.

Example:

```sql
SELECT i.name FROM system.insights AS i INNER JOIN system.dashboard_tiles AS t ON i.id = t.insight_id WHERE t.dashboard_id = 1
```

#### Analytical data

Prefer using analytical functions and subqueries for joins. Do not use raw joins on the events table.

##### How you should join data

<example>
User: Find ai traces with feedback
Assistant:
```sql
SELECT
 g.properties.$ai_trace_id as trace_id
FROM events AS g
WHERE
  timestamp >= now() - INTERVAL 1 WEEK
  AND g.event = '$ai_generation'
  AND trace_id IN (SELECT properties.$ai_trace_id FROM events WHERE event = '$ai_feedback' AND timestamp >= now() - INTERVAL 1 WEEK)
```
<reasoning>A subquery is used instead a JOIN clause. Both queries have the timestamp filters.</reasoning>
</example>

##### How you should NOT join data

<example>
User: Find ai traces with feedback
Assistant:
```sql
SELECT
 g.properties.$ai_trace_id
FROM events AS g
INNER JOIN (SELECT properties.$ai_trace_id as trace_id FROM events WHERE event = '$ai_feedback') AS f
ON g.properties.$ai_trace_id = f.trace_id
WHERE g.event = '$ai_generation'
```
<reasoning>Join is not necessary here. The assistant could've used a subquery.</reasoning>
</example>

### Other constraints

- All queries are limited to 100 rows, so you should use LIMIT and OFFSET for pagination.
- You should cherry-pick `properties` of events, persons, or groups, so we don't get OOMs.

## HogQL Differences from Standard SQL

### Property access

```sql
-- Simple keys
properties.foo.bar

-- Keys with special characters
properties.foo['bar-baz']
```

### Unsupported/changed functions

| Don't use                          | Use instead                                                                                     |
| ---------------------------------- | ----------------------------------------------------------------------------------------------- |
| `toFloat64OrNull()`, `toFloat64()` | `toFloat()`                                                                                     |
| `toDateOrNull(timestamp)`          | `toDate(timestamp)`                                                                             |
| `LAG()`, `LEAD()`                  | `lagInFrame()`, `leadInFrame()` with `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` |
| `count(*)`                         | `count()`                                                                                       |
| `cardinality(bitmap)`              | `bitmapCardinality(bitmap)`                                                                     |
| `split()`                          | `splitByChar()`, `splitByString()`                                                              |

### JOIN constraints

Relational operators (`>`, `<`, `>=`, `<=`) are **forbidden** in JOIN clauses. Use CROSS JOIN with WHERE:

```sql
-- Wrong
JOIN persons p ON e.person_id = p.id AND e.timestamp > p.created_at

-- Correct
CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at
```

### Other rules

- WHERE clause must come after all JOINs
- No semicolons at end of queries
- `toStartOfWeek(timestamp, 1)` for Monday start (numeric, not string)
- Always handle nulls before array functions: `splitByChar(',', coalesce(field, ''))`
- Performance: always filter `events` by timestamp

### Variables (optional filters)

Use the `variables` namespace with guards:

```sql
-- Optional org filter
AND (coalesce(variables.org, '') = '' OR properties.org = variables.org)

-- Optional browser filter
AND (variables.browser IS NULL OR properties.$browser = variables.browser)
```

---

## Examples

**Weekly active users with activation event:**

```sql
SELECT week_of, countIf(weekly_event_count >= 3)
FROM (
   SELECT person.id AS person_id, toStartOfWeek(timestamp) AS week_of, count() AS weekly_event_count
   FROM events
   WHERE event = 'activation_event'
     AND properties.$current_url = 'https://example.com/foo/'
     AND toStartOfWeek(now()) - INTERVAL 8 WEEK <= timestamp
     AND timestamp < toStartOfWeek(now())
   GROUP BY person.id, week_of
)
GROUP BY week_of
ORDER BY week_of DESC
```

**Find cohorts by name:**

```sql
SELECT id, name, count FROM system.cohorts WHERE name ILIKE '%paying%' AND NOT deleted
```

**List feature flags:**

```sql
SELECT key, name, rollout_percentage
FROM system.feature_flags
WHERE NOT deleted
ORDER BY created_at DESC
LIMIT 20
```

## Available HogQL functions

Verify what functions are available using [the reference list](./references/available-functions.md) with suitable bash commands.
