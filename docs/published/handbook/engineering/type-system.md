---
title: Type system guide
sidebar: Docs
showTitle: true
---

PostHog has two type generation systems that keep frontend and backend in sync. This guide covers both directions and best practices for each.

## Overview

| Flow               | Source of truth        | Generated output     | Used for                                                  |
| ------------------ | ---------------------- | -------------------- | --------------------------------------------------------- |
| Backend → Frontend | Django serializers     | TypeScript (Orval)   | API responses                                             |
| Frontend → Backend | TypeScript `schema.ts` | Pydantic `schema.py` | Query types (HogQL, filters, insights), some legacy types |

These are independent systems. Don't conflate them.

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

### Regenerating types

Run after changing serializers, viewsets, or `@extend_schema` decorators:

```bash
hogli build:openapi
```

CI will fail if generated types are stale.

### Adding a new product's API

1. Ensure `products/your_product/frontend/` directory exists
2. Put your ViewSet in `products/your_product/backend/`
3. Run `hogli build:openapi`
4. Types appear in `products/your_product/frontend/generated/`

ViewSets in `products/*/backend/` are **automatically tagged** based on their module path. Manual `@extend_schema(tags=[...])` is not needed for products.

Serializers are the source of truth for response types. Use explicit field types and `help_text` where helpful.

### Documenting query parameters

For endpoints with query parameters, use `@validated_request` (WIP pattern):

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
    status = request.validated_query_data.get("status")  # Use validated data
    ...
```

This validates inputs AND documents the endpoint for OpenAPI. Use `request.validated_query_data`, not manual `request.query_params` parsing.

### Troubleshooting

**Types not generating?** Ensure your ViewSet is in `products/your_product/backend/` and the `products/your_product/frontend/` directory exists. Auto-tagging happens based on module path.

**Wrong type shapes?** The serializer is the source of truth. Use `@extend_schema_field` for custom `SerializerMethodField` types.

**CI failing?** Run `hogli build:openapi` locally and commit the regenerated files.

### Design decisions

**Why commit generated files?** Makes type changes visible in PRs, lets CI catch drift, avoids needing Django running for frontend builds.

**Why `Api` suffix?** Prevents collisions with handwritten types. If you see `Api`, it came from the backend.

**Why no deduplication across products?** Keeps products isolated—changing one serializer won't affect another's types.

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

If you need a type from the backend in the frontend, define it in serializers and use the backend → frontend generation system.

For backend-only types, define Pydantic models directly in your own product e.g. in a `domain_types.py` file.

## Help clean up

We're migrating from manually-defined API types to generated ones and also clean up ownership. You can help:

### Quick wins

1. **Find manual types that duplicate generated ones** – Search for interfaces like `Dashboard`, `Survey`, `FeatureFlag` in `frontend/src/types/` that now have generated `DashboardApi`, `SurveyApi` equivalents
2. **Replace API call return types** – If you see `api.get<ManualType>(...)`, switch to using the generated functions and types

### When touching existing code

- If a file imports manual types for API responses, consider migrating to generated types
- Add adapter functions where the UI needs a different shape than the API provides
- Don't mix manual and generated types for the same entity in the same file
