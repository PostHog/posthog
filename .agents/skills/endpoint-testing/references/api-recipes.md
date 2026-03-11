# API recipes

All examples use the local dev API key and assume `$TEAM_ID` is set.

```bash
API_KEY="phx_dev_local_test_api_key_1234567890abcdef"
BASE="http://localhost:8000"
TEAM_ID=$(psql posthog -tAc "SELECT id FROM posthog_team LIMIT 1")
AUTH="-H 'Authorization: Bearer $API_KEY'"
```

## Create an endpoint

### HogQL query

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my_pageviews",
    "query": {
      "kind": "HogQLQuery",
      "query": "SELECT count() AS total, toStartOfDay(timestamp) AS day FROM events WHERE event = '\''$pageview'\'' GROUP BY day ORDER BY day DESC LIMIT 30"
    },
    "description": "Daily pageview counts"
  }'
```

### HogQL query with variables

Variables require an `InsightVariable` to exist first.
Create the variable, then reference it in the query.

```bash
# Step 1: Create the InsightVariable
VAR_RESPONSE=$(curl -s -X POST "$BASE/api/environments/$TEAM_ID/insight_variables/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Event Name",
    "code_name": "event_name",
    "type": "String",
    "default_value": "$pageview"
  }')
VAR_ID=$(echo "$VAR_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Step 2: Create endpoint referencing the variable
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "events_by_name",
    "query": {
      "kind": "HogQLQuery",
      "query": "SELECT count() AS total FROM events WHERE event = {variables.event_name}",
      "variables": {
        "'"$VAR_ID"'": {
          "variableId": "'"$VAR_ID"'",
          "code_name": "event_name",
          "value": "$pageview"
        }
      }
    }
  }'
```

### Insight query (TrendsQuery)

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "pageview_trend",
    "query": {
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
        "date_from": "-7d"
      }
    }
  }'
```

### Insight query with breakdown

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "pageviews_by_browser",
    "query": {
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
  }'
```

## List endpoints

```bash
curl -s "$BASE/api/environments/$TEAM_ID/endpoints/" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool
```

## Retrieve an endpoint

```bash
curl -s "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool
```

### Retrieve a specific version

```bash
curl -s "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/?version=1" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool
```

## Update an endpoint

### Change query (creates new version)

```bash
curl -s -X PATCH "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "kind": "HogQLQuery",
      "query": "SELECT count() AS total, toStartOfDay(timestamp) AS day FROM events WHERE event = '\''$pageview'\'' GROUP BY day ORDER BY day DESC LIMIT 60"
    }
  }'
```

### Update description or cache age

```bash
curl -s -X PATCH "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Updated description",
    "cache_age_seconds": 3600
  }'
```

### Deactivate

```bash
curl -s -X PATCH "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

## Enable materialization

```bash
curl -s -X PATCH "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "is_materialized": true,
    "sync_frequency": "24hour"
  }'
```

Valid `sync_frequency` values: `"5min"`, `"10min"`, `"30min"`, `"1hour"`, `"2hour"`, `"6hour"`, `"12hour"`, `"24hour"`

## Disable materialization

```bash
curl -s -X PATCH "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"is_materialized": false}'
```

## Execute an endpoint

### Basic execution

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

### Execute with variables (HogQL endpoint)

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/events_by_name/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "variables": {
      "event_name": "$pageleave"
    }
  }'
```

### Execute with breakdown filter (insight endpoint)

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/pageviews_by_browser/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "variables": {
      "$browser": "Chrome"
    }
  }'
```

### Execute specific version

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"version": 1}'
```

### Execute with pagination (HogQL only)

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 10, "offset": 0}'
```

Response includes `hasMore`, `limit`, and `offset` fields.

### Execute with refresh modes

```bash
# Use cache (default)
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"refresh": "cache"}'

# Force fresh execution (bypass cache, still use materialization if available)
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"refresh": "force"}'

# Direct execution (bypass both cache and materialization)
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"refresh": "direct"}'
```

### Execute with debug info

```bash
curl -s -X POST "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"debug": true}'
```

Debug mode preserves: `calculation_trigger`, `cache_key`, `explain`, `modifiers`, `resolved_date_range`, `timings`, `hogql`.

## Delete an endpoint

```bash
curl -s -X DELETE "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/" \
  -H "Authorization: Bearer $API_KEY"
# Returns 204 No Content
```

## GET-based execution

All run parameters can also be passed as query params:

```bash
curl -s "$BASE/api/environments/$TEAM_ID/endpoints/my_pageviews/run/?limit=5&offset=0&version=1" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool
```
