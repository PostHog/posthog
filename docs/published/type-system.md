---
title: Type system guide
sidebar: Docs
showTitle: true
---

> **See also:** [Frontend coding conventions](/docs/contribute/frontend-coding) for general frontend guidelines, [Developing locally](/docs/contribute/developing-locally) for setup instructions.

PostHog has two type generation systems that keep frontend and backend in sync. This guide covers both directions and best practices for each.

## Overview

| Flow               | Source of truth        | Generated output     | Used for                               |
| ------------------ | ---------------------- | -------------------- | -------------------------------------- |
| Backend → Frontend | Django serializers     | TypeScript (Orval)   | API responses                          |
| Frontend → Backend | TypeScript `schema.ts` | Pydantic `schema.py` | Query types (HogQL, filters, insights) |

These are independent systems. Don't conflate them.

---

## Backend → Frontend (API responses)

We use [Orval](https://orval.dev/) to generate TypeScript types and API client functions from our OpenAPI schema.

### Ownership

- **Backend owns response types** – Generated from Django serializers via OpenAPI
- **Frontend owns request/query types** – Handwritten types for queries, filters, UI state
- Do not manually redefine backend response types in frontend code

### Where types live

| Type                | Location                                 | Editable? |
| ------------------- | ---------------------------------------- | --------- |
| Generated API types | `products/<product>/frontend/generated/` | No        |
| Core API types      | `frontend/src/generated/core/`           | No        |
| Handwritten types   | `frontend/src/types/`                    | Yes       |

Never edit files in `generated/` – they're overwritten on regeneration.

### Naming conventions

- Generated schema types end with `Api` suffix: `TaskApi`, `SurveyApi`, `DashboardApi`
- Operation response types follow Orval naming: `tasksListResponse200`, `tasksCreateResponse201`
- Handwritten types never use the `Api` suffix

This prevents name collisions between generated and manual types.

### Using generated types

```typescript
// Import from generated
import { type TaskApi, tasksCreate, tasksList } from 'products/tasks/frontend/generated'

// Call the API
const response = await tasksList(projectId, { stage: 'open' })
const tasks: TaskApi[] = response.data.results

// Create a task
const newTask = await tasksCreate(projectId, { title: 'Fix bug', description: '...' })
```

### Converting API types for UI

If the UI needs a different shape, convert explicitly:

```typescript
function convertApiTaskToTask(api: TaskApi): Task {
  return {
    id: api.id,
    title: api.title,
    // ... transform as needed
  }
}
```

### Regenerating types

Run after changing serializers, viewsets, or `@extend_schema` decorators:

```bash
hogli build:openapi
```

CI will fail if generated types are stale.

> **Tip:** Use `ProductKey` enum values (not strings) when tagging endpoints. This provides type safety and IDE autocomplete. See `posthog/schema.py` for available keys.

### Adding a new product's API

1. Add `@extend_schema(tags=[ProductKey.YOUR_PRODUCT])` to your viewset
2. Ensure `products/your_product/frontend/` directory exists
3. Run `hogli build:openapi`
4. Types appear in `products/your_product/frontend/generated/`

### Documenting your API for type generation

The OpenAPI schema is generated from your Django views and serializers. Well-documented endpoints produce accurate TypeScript types.

#### Tag your ViewSet

Use the `ProductKey` enum for type safety:

```python
from posthog.schema import ProductKey
from posthog.api.documentation import extend_schema

@extend_schema(tags=[ProductKey.YOUR_PRODUCT])
class YourViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = YourSerializer
    ...
```

#### Define clear serializers

Serializers are the source of truth for response types:

```python
class YourItemSerializer(serializers.ModelSerializer):
    # Explicit field definitions improve generated types
    created_at = serializers.DateTimeField()
    metadata = serializers.JSONField(help_text="Additional item metadata")

    class Meta:
        model = YourModel
        fields = ["id", "name", "created_at", "metadata"]
```

Tips:

- Add `help_text` for fields that need documentation
- Use explicit field types rather than relying on auto-detection
- For nested relationships, define nested serializers

#### Document query parameters

For endpoints with query parameters, create query serializers:

```python
class YourListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["active", "archived"],
        required=False,
        help_text="Filter by status"
    )
    limit = serializers.IntegerField(required=False, default=100)
```

Then use `@extend_schema` on the action:

```python
@extend_schema(parameters=[YourListQuerySerializer])
def list(self, request, *args, **kwargs):
    ...
```

### Advanced: Request validation with @validated_request

> **Note:** This pattern is a work in progress. We're iterating on it as we move fast. Feedback and improvements welcome!

For endpoints that need validated query parameters exposed to the view, use `@validated_request`:

```python
from posthog.api.utils import validated_request

class MyQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["active", "archived"], required=False)
    limit = serializers.IntegerField(default=100, min_value=1)

@validated_request(
    query_serializer=MyQuerySerializer,
    responses={200: MyResponseSerializer(many=True)},
)
@action(methods=["GET"], detail=False)
def my_action(self, request, **kwargs):
    # Access validated data - don't parse request.query_params manually!
    status = request.validated_query_data.get("status")
    limit = request.validated_query_data.get("limit")
    ...
```

Key points:

- The decorator validates inputs AND documents the endpoint for OpenAPI
- Always use `request.validated_query_data`, never manual `request.query_params` parsing
- Response serializers ensure the schema matches what you actually return

### Troubleshooting

**Types not generating for my endpoint?**

- Check that your ViewSet has `@extend_schema(tags=[ProductKey.YOUR_PRODUCT])`
- Verify `products/your_product/frontend/` directory exists
- Run `hogli build:openapi` and check for warnings

**Generated types have wrong shapes?**

- The serializer is the source of truth—check your field definitions
- Use `@extend_schema_field` for custom SerializerMethodField types
- For complex responses, define explicit response serializers

**CI failing with "OpenAPI types are out of date"?**

- Run `hogli build:openapi` locally
- Commit the regenerated files in `products/*/frontend/generated/`

### Design decisions

**Why generated files are committed:** Generated types are checked into git rather than generated at build time. This makes type changes visible in PRs, lets CI catch stale types, and avoids requiring the full backend stack (Django, database) just to run frontend builds or type checks.

**Why types aren't deduplicated:** Many OpenAPI schemas share common types (e.g., `UserBasic` appears in multiple endpoints). We intentionally don't deduplicate these across products. Each product gets its own copy with the `Api` suffix. This keeps products isolated—a change to one product's serializer won't affect another's types—and avoids complex cross-product import graphs. The duplication cost is negligible (a few KB) compared to the maintenance benefit.

**Why the `Api` suffix:** Generated types use `TaskApi`, not `Task`. This prevents collisions with handwritten frontend types and makes it obvious at the import site whether you're using a generated or manual type. If you see `Api`, it came from the backend.

---

## Frontend → Backend (query types)

Query types like `TrendsQuery`, `FunnelsQuery`, and HogQL filters are defined in TypeScript and generated to Python.

### How it works

1. **Source:** `frontend/src/queries/schema.ts` (TypeScript interfaces)
2. **Intermediate:** `frontend/src/queries/schema.json` (JSON Schema)
3. **Output:** `posthog/schema.py` (Pydantic models)

### Regenerating

```bash
hogli build:schema
```

This runs:

1. `build:schema-json` – TS → JSON Schema
2. `build:schema-python` – JSON Schema → Pydantic

### When to add types here

Add to `schema.ts` when you need a type that:

- Is sent from frontend to backend as a query/filter
- Needs validation on the backend
- Is part of HogQL or insight definitions
- Do not add types that are only used in the frontend UI
- Do not add types just because you need a type in Python – use handwritten types for backend-only logic

## Backend-only types

Not everything needs to go through the type generation systems.

### Use DRF serializers directly

For API responses that don't need complex frontend types:

- Simple CRUD endpoints
- Internal/admin APIs
- One-off responses

The serializer becomes the source of truth, and Orval generates the frontend types.

### When to define Pydantic models directly

For backend-only domain logic:

- Internal data structures
- Background job payloads
- Inter-service communication

Don't put these in `schema.py` – that file is for generated types only.

```python
# In your product's models or types module
from pydantic import BaseModel

class InternalTaskState(BaseModel):
    """Backend-only type, not exposed to frontend."""
    task_id: str
    retry_count: int
    last_error: str | None
```

## Help clean up

We're migrating from manually-defined API types to generated ones and also clean up ownership. You can help:

### Quick wins

1. **Find manual types that duplicate generated ones** – Search for interfaces like `Dashboard`, `Survey`, `FeatureFlag` in `frontend/src/types/` that now have generated `DashboardApi`, `SurveyApi` equivalents
2. **Replace API call return types** – If you see `api.get<ManualType>(...)`, switch to using the generated functions and types

### When touching existing code

- If a file imports manual types for API responses, consider migrating to generated types
- Add adapter functions where the UI needs a different shape than the API provides
- Don't mix manual and generated types for the same entity in the same file
