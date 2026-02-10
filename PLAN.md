# Endpoints MaxTools Implementation Plan

## Overview

Add two MaxTools for the endpoints product: `CreateEndpointTool` and `UpdateEndpointTool`.
These tools let Max create and manage API endpoints from insights or SQL queries,
with materialization support and context injection from the current page.

## Key Design Decision: Reuse the Existing API

The `EndpointViewSet` already has all validation, creation, versioning, materialization,
and activity logging logic. **The tools should call the viewset internally**, not reimplement
any of it. Each tool constructs a DRF `Request`, calls the viewset method, and translates the
response into the MaxTool `(content, artifact)` format.

Pattern:
```python
from rest_framework.test import APIRequestFactory

@database_sync_to_async
def _call_create():
    factory = APIRequestFactory()
    request = factory.post("/fake/", data=request_data, format="json")
    force_authenticate(request, user=self._user)
    view = EndpointViewSet.as_view({"post": "create"}, team=self._team, ...)
    response = view(request)
    return response
```

This ensures:
- Name validation, HogQL syntax validation, cache_age range checks — all reused
- Version creation on query change — automatic
- Materialization auto-enable for HogQL queries — automatic
- Activity logging — automatic
- No logic drift between API and tools

## Tools

### 1. `CreateEndpointTool`

**Args** (`CreateEndpointArgs`):
- `name: str` — URL-safe endpoint name
- `query: dict` — The query dict (HogQL or insight query, from context or agent-constructed)
- `description: str | None` — optional
- `cache_age_seconds: int | None` — optional, 300-86400
- `is_materialized: bool | None` — optional, defaults based on query type
- `sync_frequency: str | None` — one of DataWarehouseSyncInterval values

**Implementation**: Build `EndpointRequest`-shaped dict, call `EndpointViewSet.create()`.
Parse the response. Return `(message, artifact_dict)`.

**Access**: `[("endpoint", "editor")]`

### 2. `UpdateEndpointTool`

**Args** (`UpdateEndpointArgs`):
- `name: str` — existing endpoint name (lookup key)
- `query: dict | None` — new query (viewset handles versioning)
- `description: str | None`
- `cache_age_seconds: int | None`
- `is_active: bool | None`
- `is_materialized: bool | None`
- `sync_frequency: str | None`

**Implementation**: Build request dict with only non-None fields,
call `EndpointViewSet.update()`. Parse response. Return `(message, artifact_dict)`.

**Access**: `[("endpoint", "editor")]`

## Files to Change

### Backend

1. **`frontend/src/queries/schema/schema-assistant-messages.ts`**
   - Add to `AssistantTool` enum:
     ```
     CreateEndpoint = 'create_endpoint',
     UpdateEndpoint = 'update_endpoint',
     ```
   - Then `pnpm run schema:build`

2. **`products/endpoints/backend/max_tools.py`** (NEW)
   - `CreateEndpointArgs` + `CreateEndpointTool`
   - `UpdateEndpointArgs` + `UpdateEndpointTool`
   - Both tools call `EndpointViewSet` internally — thin wrappers

3. **`products/endpoints/backend/test/test_max_tools.py`** (NEW)
   - Tests for both tools (parameterized where possible)

### Frontend

4. **`frontend/src/scenes/max/max-constants.tsx`**
   - Add `create_endpoint` and `update_endpoint` to `TOOL_DEFINITIONS`
   - Associate with `product: Scene` and `modes`

5. **Frontend context registration** (insights page, SQL editor, endpoint detail page)
   - Use `useMaxTool` hook to register tools with current query/endpoint context
   - Insight page: register `create_endpoint` with `{ current_query: insightQuery }`
   - SQL editor: register `create_endpoint` with `{ current_query: sqlQuery }`
   - Endpoint detail page: register `update_endpoint` with current endpoint state

### Agent Mode Integration

6. **`ee/hogai/core/agent_modes/presets/sql.py`**
   - Add tools to SQL mode toolkit

7. **Feature flag** gating (e.g. `ai-endpoints-tools`)

## Context Injection

When on an insight or SQL page, the frontend registers the tool with the current query
as context. The tool's `context_prompt_template` tells the agent this context is available.
The agent can then pass it directly as the `query` arg to `create_endpoint`.

## What We're NOT Doing

- No new `AgentMode.Endpoints` — tools live in SQL mode
- No reimplementation of validation/creation/materialization logic — call the viewset
- No versioning tools (list versions, rollback) — can add later
- No run/execute endpoint tool — users use the REST API
- No OpenAPI spec generation tool — UI-only feature
