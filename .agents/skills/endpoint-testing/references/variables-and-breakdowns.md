# Variables and breakdowns

## InsightVariable lifecycle

Variables are managed as `InsightVariable` records and referenced in queries.

### Creating a variable via API

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/insight_variables/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Event Name",
    "code_name": "event_name",
    "type": "String",
    "default_value": "$pageview"
  }'
```

Variable types: `String`, `Number`, `Boolean`, `List`, `Date`

### Variable in a HogQL query

The query uses `{variables.code_name}` syntax.
The `variables` dict maps variable UUIDs to their metadata.

```json
{
  "kind": "HogQLQuery",
  "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
  "variables": {
    "550e8400-e29b-41d4-a716-446655440000": {
      "variableId": "550e8400-e29b-41d4-a716-446655440000",
      "code_name": "event_name",
      "value": "$pageview"
    }
  }
}
```

### Variable sync behavior

When creating or updating an endpoint with a HogQL query:

1. The API parses the query for `{variables.X}` placeholders
2. It matches placeholders to existing `InsightVariable` records by `code_name`
3. Missing variables are looked up in the team's `InsightVariable` table
4. Variable metadata is synced into the query's `variables` dict
5. If a variable has no value, the `InsightVariable.default_value` is used

### Validation rules

- Every `{variables.X}` placeholder must have a matching variable definition
- Variable IDs must be valid UUIDs
- Variable IDs must correspond to existing `InsightVariable` records for the team

## Variables at execution time

### Passing variables in run requests

For HogQL endpoints, pass variables by `code_name`:

```json
{ "variables": { "event_name": "$pageleave" } }
```

For insight endpoints with breakdowns, pass the breakdown property name:

```json
{ "variables": { "$browser": "Chrome" } }
```

### Allowed variables

What variables you can pass depends on endpoint type and materialization:

| Endpoint type | Materialized | Allowed variables                                 |
| ------------- | ------------ | ------------------------------------------------- |
| HogQL         | No           | All `code_name`s from query `variables`           |
| HogQL         | Yes          | All materialized variable `code_name`s            |
| Insight       | No           | Breakdown property name + `date_from` + `date_to` |
| Insight       | Yes          | Breakdown property name only                      |

### Required variables for materialized endpoints

Materialized endpoints with variables **require** all variable values to be provided.
This prevents data leakage — without this check, a materialized table
with no WHERE filter would return all data.

## Materialization transforms

### Single equality variable

```text
Original:  SELECT count() AS total FROM events WHERE event = {variables.event_name} GROUP BY day
Transform: SELECT count() AS total, event AS event_name FROM events GROUP BY day, event
```

### Range variables (same column)

```text
Original:  SELECT count() FROM events WHERE hour >= {variables.start} AND hour < {variables.end}
Transform: SELECT count(), hour AS start, hour AS end FROM events GROUP BY hour
```

GROUP BY is deduplicated — `hour` appears once even though two variables reference it.

### Property access variable

```text
Original:  SELECT count() FROM events WHERE properties.$browser = {variables.browser}
Transform: SELECT count(), JSONExtractString(properties, '$browser') AS browser FROM events GROUP BY JSONExtractString(properties, '$browser')
```

### Variable with function wrapping

```text
Original:  SELECT count() FROM events WHERE toDate(timestamp) >= toDate({variables.start_date})
Transform: SELECT count(), toDate(timestamp) AS start_date FROM events GROUP BY toDate(timestamp)
```

At execution time, the wrapper functions are applied:

```sql
SELECT * FROM materialized_table WHERE start_date >= toDate('2026-01-01')
```

### Bucket overrides

EndpointVersion supports `bucket_overrides` — per-column function overrides
for range variable materialization (e.g., `{"timestamp": "toStartOfHour"}`).

## Breakdowns

### How breakdowns work in insight endpoints

Breakdowns split results by a property value.
Only **single** breakdowns are supported for materialization.

### Breakdown filter formats

Legacy format:

```json
{ "breakdownFilter": { "breakdown": "$browser", "breakdown_type": "event" } }
```

New format (preferred):

```json
{ "breakdownFilter": { "breakdowns": [{ "property": "$browser", "type": "event" }] } }
```

### Breakdown columns in materialized tables

| Query type      | Breakdown column  | Format                    |
| --------------- | ----------------- | ------------------------- |
| TrendsQuery     | `breakdown_value` | `Array(Nullable(String))` |
| RetentionQuery  | `breakdown_value` | `Array(Nullable(String))` |
| FunnelsQuery    | `final_prop`      | `Array(Nullable(String))` |
| LifecycleQuery  | Not supported     | —                         |
| StickinessQuery | Not supported     | —                         |
| PathsQuery      | Not supported     | —                         |

### Filtering materialized breakdowns

Because breakdown columns are arrays, filtering uses `has()`:

```sql
-- TrendsQuery / RetentionQuery
SELECT * FROM materialized_table WHERE has(breakdown_value, 'Chrome')

-- FunnelsQuery
SELECT * FROM materialized_table WHERE has(final_prop, 'Chrome')
```

### Passing breakdown as variable at execution time

```bash
# For an insight endpoint with breakdownFilter on $browser
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/pageviews_by_browser/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"variables": {"$browser": "Chrome"}}'
```

The variable name must match the breakdown property name exactly.

## Common validation errors

| Error                                                        | Cause                                                  | Fix                                                 |
| ------------------------------------------------------------ | ------------------------------------------------------ | --------------------------------------------------- |
| `Query references undefined variable(s): X`                  | Placeholder `{variables.X}` but no variable definition | Create InsightVariable with matching `code_name`    |
| `Variable ID(s) not valid UUIDs`                             | Variable key is not a UUID                             | Use actual UUID from InsightVariable                |
| `Variable ID(s) not found`                                   | UUID doesn't match any InsightVariable                 | Check InsightVariable exists for the team           |
| `Variable 'X' not found in query`                            | Run request passes unknown variable                    | Check allowed variables for the endpoint            |
| `Variables not supported: Variable not used in WHERE clause` | Variable not materializable                            | Ensure variable is in WHERE with supported operator |
| `Variables not supported: Variable used in HAVING clause`    | HAVING clause variables                                | Move variable to WHERE clause                       |
| `Multiple breakdowns not supported for materialization`      | >1 breakdown in breakdownFilter                        | Use single breakdown                                |
