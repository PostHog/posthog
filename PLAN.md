# Endpoints MaxTools Implementation Plan

## Overview

Add two MaxTools for the endpoints product: `CreateEndpointTool` and `UpdateEndpointTool`.
These tools let Max create and manage API endpoints from insights or SQL queries,
with materialization support and context injection from the current page.

## Key Design Decision: Extract Service Functions from the ViewSet

The `EndpointViewSet` already has all validation, creation, versioning, materialization,
and activity logging logic. Rather than reimplementing or faking HTTP requests, we
**extract the core logic into service functions** that both the viewset and the tools call.

### Step 1: Extract `products/endpoints/backend/services.py` (NEW)

Pull the business logic out of `EndpointViewSet.create()` and `EndpointViewSet.update()`
into standalone functions:

```python
def create_endpoint(
    *, team: Team, user: User, name: str, query: dict,
    description: str = "", cache_age_seconds: int | None = None,
    is_materialized: bool | None = None,
    sync_frequency: DataWarehouseSyncInterval | None = None,
    derived_from_insight: str | None = None,
    is_active: bool = True,
) -> tuple[Endpoint, EndpointVersion]:
    """Create an endpoint + initial version. Handles validation,
    materialization, and activity logging."""
    ...

def update_endpoint(
    *, team: Team, user: User, endpoint: Endpoint,
    query: dict | None = None, description: str | None = None,
    cache_age_seconds: int | None = None, is_active: bool | None = None,
    is_materialized: bool | None = None,
    sync_frequency: DataWarehouseSyncInterval | None = None,
    target_version: int | None = None,
) -> tuple[Endpoint, EndpointVersion]:
    """Update an endpoint. Handles versioning, materialization,
    and activity logging."""
    ...
```

### Step 2: Refactor `EndpointViewSet` to call these functions

The viewset methods become thin HTTP wrappers:
```python
def create(self, request, *args, **kwargs):
    data = self.get_model(upgrade(request.data), EndpointRequest)
    endpoint, version = create_endpoint(team=self.team, user=request.user, ...)
    return Response(self._serialize(endpoint, request), status=201)
```

### Step 3: MaxTools call the same service functions

```python
class CreateEndpointTool(MaxTool):
    async def _arun_impl(self, name, query, ...):
        endpoint, version = await database_sync_to_async(create_endpoint)(
            team=self._team, user=self._user, name=name, query=query, ...
        )
        return (message, artifact)
```

This ensures:
- Name validation, HogQL syntax validation, cache_age range checks — all shared
- Version creation on query change — shared
- Materialization auto-enable — shared
- Activity logging — shared
- No logic drift between API and tools
- No fake HTTP requests

## Tools

### 1. `CreateEndpointTool`

**Args** (`CreateEndpointArgs`):
- `name: str` — URL-safe endpoint name
- `query: dict` — The query dict (HogQL or insight query, from context or agent-constructed)
- `description: str | None` — optional
- `cache_age_seconds: int | None` — optional, 300-86400
- `is_materialized: bool | None` — optional, defaults based on query type
- `sync_frequency: str | None` — one of DataWarehouseSyncInterval values

**Implementation**: Call `create_endpoint()` service function.
Return `(message, artifact_dict)` with endpoint id, name, path.

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

**Implementation**: Call `update_endpoint()` service function with only non-None fields.
Return `(message, artifact_dict)` with updated state.

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

2. **`products/endpoints/backend/services.py`** (NEW)
   - `create_endpoint()` and `update_endpoint()` — extracted from viewset
   - All validation, versioning, materialization, activity logging lives here

3. **`products/endpoints/backend/api.py`** (REFACTOR)
   - `EndpointViewSet.create()` and `.update()` become thin wrappers calling services

4. **`products/endpoints/backend/max_tools.py`** (NEW)
   - `CreateEndpointArgs` + `CreateEndpointTool`
   - `UpdateEndpointArgs` + `UpdateEndpointTool`
   - Both call service functions — thin wrappers

5. **`products/endpoints/backend/test/test_max_tools.py`** (NEW)
   - Tests for both tools (parameterized where possible)

### Frontend

6. **`frontend/src/scenes/max/max-constants.tsx`**
   - Add `create_endpoint` and `update_endpoint` to `TOOL_DEFINITIONS`
   - Associate with `product: Scene` and `modes`

7. **Frontend context registration** (insights page, SQL editor, endpoint detail page)
   - Use `useMaxTool` hook to register tools with current query/endpoint context
   - Insight page: register `create_endpoint` with `{ current_query: insightQuery }`
   - SQL editor: register `create_endpoint` with `{ current_query: sqlQuery }`
   - Endpoint detail page: register `update_endpoint` with current endpoint state

### Agent Mode Integration

8. **`ee/hogai/core/agent_modes/presets/sql.py`**
   - Add tools to SQL mode toolkit

9. **Feature flag** gating (e.g. `ai-endpoints-tools`)

## Context Injection

When on an insight or SQL page, the frontend registers the tool with the current query
as context. The tool's `context_prompt_template` tells the agent this context is available.
The agent can then pass it directly as the `query` arg to `create_endpoint`.

## What We're NOT Doing

- No new `AgentMode.Endpoints` — tools live in SQL mode
- No reimplementation of validation/creation/materialization logic — shared service functions
- No versioning tools (list versions, rollback) — can add later
- No run/execute endpoint tool — users use the REST API
- No OpenAPI spec generation tool — UI-only feature
