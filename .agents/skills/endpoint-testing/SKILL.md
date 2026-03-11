---
name: endpoint-testing
description: >
  Testing PostHog endpoints product via the local API.
  Use when creating, materializing, executing, or validating endpoints
  against the local dev stack.
  Covers CRUD operations, materialization workflows, variable and breakdown
  validation, HogQL and insight query construction, and database inspection
  with psql and the dev API key.
---

# Testing endpoints

## Overview

PostHog **endpoints** turn saved queries (HogQL or insight-based) into
reusable REST API paths:

```text
POST /api/environments/{team_id}/endpoints/              → create
GET  /api/environments/{team_id}/endpoints/               → list
GET  /api/environments/{team_id}/endpoints/{name}/        → retrieve
PATCH /api/environments/{team_id}/endpoints/{name}/       → update
DELETE /api/environments/{team_id}/endpoints/{name}/      → delete (soft)
POST /api/environments/{team_id}/endpoints/{name}/run/    → execute
GET  /api/environments/{team_id}/endpoints/{name}/run/    → execute (GET)
```

Endpoints support **versioning**, **materialization** (pre-computed results
in S3/ClickHouse), and **variables** (dynamic WHERE-clause parameters).

## Quick start

```bash
# Local dev API key (always available after `hogli dev:api-key`)
API_KEY="phx_dev_local_test_api_key_1234567890abcdef"
BASE="http://localhost:8000"

# Find team_id from the local database
TEAM_ID=$(psql posthog -tAc "SELECT id FROM posthog_team LIMIT 1")
```

## When to use this skill

- Creating endpoints and verifying they appear in the database
- Testing materialization enable/disable and checking saved_query status
- Executing endpoints with variables and validating results
- Constructing HogQL or insight queries for use in endpoints
- Debugging variable or breakdown filtering in materialized execution
- Verifying endpoint state via psql after API operations

## Key concepts

### Endpoint lifecycle

1. **Create** — `POST .../endpoints/` with a `query` (HogQL or insight)
2. **Materialize** — `PATCH .../endpoints/{name}/` with `is_materialized: true`
3. **Execute** — `POST .../endpoints/{name}/run/` with optional `variables`
4. **Update** — `PATCH .../endpoints/{name}/` with new `query` (creates new version)
5. **Delete** — `DELETE .../endpoints/{name}/` (soft delete)

### Variables

Variables are dynamic parameters in HogQL queries.
They require an `InsightVariable` record and use `{variables.code_name}` placeholder syntax.

### Materialization

Materialization pre-computes query results.
When materialized, variable columns are added to SELECT and GROUP BY,
and the WHERE clause containing the variable is removed.
At execution time, filters are applied against the materialized table.

### Breakdowns (insight queries)

For insight queries (TrendsQuery, FunnelsQuery, RetentionQuery),
breakdowns allow filtering by a single property.
When materialized, breakdown values are stored in `breakdown_value` or `final_prop` array columns.

## Reference files

Detailed recipes and patterns are in the `references/` subdirectory:

- [api-recipes.md](references/api-recipes.md) — curl commands for every endpoint operation
- [query-patterns.md](references/query-patterns.md) — HogQL and insight query construction
- [database-inspection.md](references/database-inspection.md) — psql queries for verification
- [variables-and-breakdowns.md](references/variables-and-breakdowns.md) — variable lifecycle, materialization transforms, breakdown filtering

## Key files in the codebase

| File                                                                | Purpose                                    |
| ------------------------------------------------------------------- | ------------------------------------------ |
| `products/endpoints/backend/api.py`                                 | ViewSet — all API actions                  |
| `products/endpoints/backend/models.py`                              | Endpoint and EndpointVersion models        |
| `products/endpoints/backend/materialization.py`                     | Variable analysis and query transformation |
| `products/endpoints/backend/tests/test_endpoint.py`                 | CRUD tests                                 |
| `products/endpoints/backend/tests/test_endpoint_execution.py`       | Execution tests with variables             |
| `products/endpoints/backend/tests/test_endpoint_materialization.py` | Materialization tests                      |
| `products/endpoints/backend/tests/test_variable_materialization.py` | Variable materialization transforms        |
| `posthog/models/insight_variable.py`                                | InsightVariable model                      |
| `posthog/management/commands/setup_local_api_key.py`                | Dev API key setup                          |
