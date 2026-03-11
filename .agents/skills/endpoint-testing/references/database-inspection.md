# Database inspection

Use `psql posthog` to inspect endpoint state after API operations.

## Find team ID

```sql
SELECT id, name FROM posthog_team LIMIT 5;
```

## List all endpoints

```sql
SELECT
    e.id,
    e.name,
    e.is_active,
    e.current_version,
    e.created_at,
    e.deleted
FROM endpoints_endpoint e
WHERE e.team_id = <TEAM_ID>
  AND (e.deleted = false OR e.deleted IS NULL)
ORDER BY e.created_at DESC;
```

## View endpoint versions

```sql
SELECT
    v.id,
    v.version,
    v.is_active,
    v.cache_age_seconds,
    v.saved_query_id,
    v.created_at,
    v.query->>'kind' AS query_kind,
    v.columns
FROM endpoints_endpointversion v
JOIN endpoints_endpoint e ON v.endpoint_id = e.id
WHERE e.name = '<ENDPOINT_NAME>'
  AND e.team_id = <TEAM_ID>
ORDER BY v.version DESC;
```

## Check materialization status

```sql
SELECT
    e.name AS endpoint_name,
    v.version,
    v.saved_query_id,
    sq.name AS saved_query_name,
    sq.status,
    sq.is_materialized,
    sq.last_run_at,
    sq.table_id,
    sq.sync_frequency_interval,
    sq.latest_error
FROM endpoints_endpointversion v
JOIN endpoints_endpoint e ON v.endpoint_id = e.id
LEFT JOIN posthog_datawarehousesavedquery sq ON v.saved_query_id = sq.id
WHERE e.name = '<ENDPOINT_NAME>'
  AND e.team_id = <TEAM_ID>
ORDER BY v.version DESC;
```

## View endpoint query content

```sql
SELECT
    v.version,
    v.query->>'kind' AS kind,
    v.query->>'query' AS hogql_query,
    v.query->'variables' AS variables,
    v.query->'breakdownFilter' AS breakdown_filter
FROM endpoints_endpointversion v
JOIN endpoints_endpoint e ON v.endpoint_id = e.id
WHERE e.name = '<ENDPOINT_NAME>'
  AND e.team_id = <TEAM_ID>
ORDER BY v.version DESC
LIMIT 1;
```

## List InsightVariables

```sql
SELECT
    id,
    name,
    code_name,
    type,
    default_value
FROM posthog_insightvariable
WHERE team_id = <TEAM_ID>
ORDER BY created_at DESC;
```

## Check variable in endpoint query

```sql
SELECT
    e.name,
    v.version,
    key AS variable_id,
    value->>'code_name' AS code_name,
    value->>'value' AS default_value,
    value->>'variableId' AS variable_uuid
FROM endpoints_endpointversion v
JOIN endpoints_endpoint e ON v.endpoint_id = e.id,
    jsonb_each(v.query->'variables') AS vars(key, value)
WHERE e.team_id = <TEAM_ID>
  AND e.name = '<ENDPOINT_NAME>'
ORDER BY v.version DESC;
```

## Check activity log for endpoint

```sql
SELECT
    al.activity,
    al.scope,
    al.detail,
    al.created_at,
    u.email AS user_email
FROM posthog_activitylog al
JOIN posthog_user u ON al.user_id = u.id
WHERE al.team_id = <TEAM_ID>
  AND al.scope = 'Endpoint'
ORDER BY al.created_at DESC
LIMIT 20;
```

## Check soft-deleted endpoints

```sql
SELECT
    id, name, deleted, deleted_at, is_active
FROM endpoints_endpoint
WHERE team_id = <TEAM_ID>
  AND deleted = true
ORDER BY deleted_at DESC;
```

## Check saved query materialized table

```sql
SELECT
    sq.name,
    sq.status,
    sq.is_materialized,
    sq.table_id,
    t.name AS table_name,
    t.url_pattern,
    t.format
FROM posthog_datawarehousesavedquery sq
LEFT JOIN posthog_datawarehousetable t ON sq.table_id = t.id
WHERE sq.team_id = <TEAM_ID>
  AND sq.origin = 'endpoint'
ORDER BY sq.created_at DESC;
```

## Verify dev API key exists

```sql
SELECT
    pak.id,
    pak.label,
    pak.mask_value,
    pak.scopes,
    u.email
FROM posthog_personalapikey pak
JOIN posthog_user u ON pak.user_id = u.id
WHERE pak.label = 'Local Development Key';
```
