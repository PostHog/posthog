---
name: adopting-generated-api-types
description: Use when migrating frontend code from manual API client calls (`api.get`, `api.create`, `api.surveys.get`, `api.dashboards.list`, `new ApiRequest()`) and handwritten TypeScript interfaces to generated API functions and types. Triggers on files importing from `lib/api`, files with `api.get<`, `api.create<`, `api.<entity>.<method>`, manual interface definitions that duplicate backend serializers, or any frontend file that constructs API URLs by hand. Covers the full replacement workflow — finding the generated equivalent, swapping imports, adapting call sites, and removing dead manual types.
---

# Adopting generated API types

## Overview

PostHog generates TypeScript API client functions and types from Django serializers via the OpenAPI pipeline:

```text
Django serializer → drf-spectacular → OpenAPI JSON → Orval → TypeScript (api.ts + api.schemas.ts + api.zod.ts)
```

Generated files live in:

- **Core:** `frontend/src/generated/core/api.ts`, `api.schemas.ts`, and `api.zod.ts`
- **Products:** `products/<product>/frontend/generated/api.ts`, `api.schemas.ts`, and `api.zod.ts`

Generated types use the `Api` suffix (`DashboardApi`, `SurveyApi`). Handwritten types never do.

This skill guides replacing manual API calls and handwritten types with generated equivalents.

## The three manual patterns to migrate

The legacy `frontend/src/lib/api.ts` (~6000 lines) has three layers, all migration targets:

### 1. High-level object API (most common)

Domain-specific convenience methods on the `api` object:

```typescript
api.surveys.get(id)
api.surveys.create(data)
api.dashboards.list()
api.cohorts.update(id, data)
api.actions.create(data)
```

These are the most widely used pattern — every entity has its own namespace with CRUD plus custom methods (e.g., `api.surveys.getResponsesCount()`, `api.dashboards.streamTiles()`).

### 2. Raw HTTP methods with manual URLs

```typescript
api.get<SomeType>(`api/projects/${id}/surveys/`)
api.create<SomeType>(`api/projects/${id}/surveys/`, data)
api.update<SomeType>(url, data)
api.put<SomeType>(url, data)
api.delete(url)
```

### 3. ApiRequest builder (fluent URL construction)

```typescript
const url = new ApiRequest().surveys().assembleFullUrl()
const response = await api.get(url)

// or directly:
await new ApiRequest().survey(surveyId).withAction('summarize_responses').create({ data })
```

All three patterns should be replaced with generated functions where available.

## When to use

- Touching a file that calls `api.<entity>.<method>()` (e.g., `api.surveys.get()`)
- Touching a file that calls `api.get<T>(...)`, `api.create<T>(...)`, etc.
- Touching a file that uses `new ApiRequest()` to build URLs
- Touching a file that imports handwritten interfaces from `~/types` for API response shapes
- Cleaning up frontend code after backend serializer improvements

## Step-by-step workflow

### 1. Identify what the manual call does

Look at the existing call and extract:

- **HTTP method** — GET, POST, PUT, PATCH, DELETE
- **Entity and action** — what resource, what operation
- **Type parameter** — the handwritten type used for the response

### 2. Find the generated equivalent

Generated function names follow the `{resource}{Action}` convention:

```text
surveysList          — GET    /api/projects/{id}/surveys/
surveysCreate        — POST   /api/projects/{id}/surveys/
surveysRetrieve      — GET    /api/projects/{id}/surveys/{id}/
surveysPartialUpdate — PATCH  /api/projects/{id}/surveys/{id}/
surveysDestroy       — DELETE /api/projects/{id}/surveys/{id}/
```

**Where to search:**

- Core endpoints: `frontend/src/generated/core/api.ts`
- Product endpoints: `products/<product>/frontend/generated/api.ts`

**Search strategies:**

1. Grep for the entity name in the generated `api.ts` files
2. Search by the `get*Url` helper functions — every generated function has a URL builder above it
3. Search `api.schemas.ts` for the type name with `Api` suffix

If no generated function exists, the backend endpoint may lack `@extend_schema` or `@validated_request`. Fix the backend first using the `improving-drf-endpoints` skill, then run `hogli build:openapi`.

**Custom actions** (like `api.surveys.summarize_responses()`) may not have generated equivalents if the backend `@action` lacks `@extend_schema`. Check generated files first; if missing, fix the backend.

### 3. Check type compatibility

Compare the handwritten type with the generated `Api` type. Key differences:

- **`readonly` modifiers** — generated types mark read-only fields
- **Optional vs required** — generated types reflect `required=` precisely
- **Nullability** — `null` types are explicit
- **Extra fields** — generated types may include fields the handwritten type omits

See [type-compatibility.md](references/type-compatibility.md) for details.

### 4. Replace the call

See [migration-patterns.md](references/migration-patterns.md) for detailed before/after examples covering:

- High-level object API (`api.surveys.get()` → `surveysRetrieve()`)
- Raw HTTP methods (`api.get<T>(url)` → generated function)
- ApiRequest builder → generated function
- Paginated list calls
- Create/update with request bodies
- Delete calls
- Kea logic loaders and listeners
- Calls with abort signals

### 5. Replace the type at usage sites

Update downstream references from the handwritten type to the generated one:

```typescript
// Before
function renderSurvey(survey: Survey): JSX.Element { ... }

// After
function renderSurvey(survey: SurveyApi): JSX.Element { ... }
```

### 6. Clean up dead types

After migrating all usages of a handwritten type:

1. Remove the type definition from `~/types` or the local file
2. Remove unused imports
3. Run `pnpm --filter=@posthog/frontend typescript:check` to verify no breakage

## Decision guide

| Scenario                                            | Action                                                                                                       |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Generated function exists                           | Replace manual call with generated function                                                                  |
| Generated type exists but function doesn't          | Use the generated type as the generic parameter on the manual call, file a follow-up to add `@extend_schema` |
| Neither exists                                      | Keep the manual pattern, fix the backend serializer/viewset first                                            |
| Custom action without generated equivalent          | Keep the `api.<entity>.<method>()` call, fix the backend `@action` annotation first                          |
| Generated type has different shape than handwritten | Adapt call sites to the generated shape — the serializer is the source of truth                              |
| Code mutates the response object                    | Use a local mutable copy: `const mutable = { ...response }` and mutate that                                  |
| Need both read and write types                      | Use `FooApi` for reads, derive write types via `Parameters<typeof fooCreate>[1]` or use `PatchedFooApi`      |

## Import conventions

```typescript
// Core generated functions — import from api.ts
import { domainsList, domainsCreate, domainsRetrieve } from '~/generated/core/api'

// Core generated types — import type from api.schemas.ts
import type { OrganizationDomainApi } from '~/generated/core/api.schemas'

// Core generated Zod schemas — import from api.zod.ts
import { DomainsCreateBody } from '~/generated/core/api.zod'

// Product generated functions — NO tilde prefix, use 'products/' path
import { surveysList, surveysRetrieve } from 'products/surveys/frontend/generated/api'
import type { SurveyApi } from 'products/surveys/frontend/generated/api.schemas'
import { SurveysCreateBody } from 'products/surveys/frontend/generated/api.zod'

// Within a product, relative imports also work
import { logsAlertsCreate } from '../generated/api'
import type { LogsAlertConfigurationApi } from '../generated/api.schemas'
import { LogsAlertsCreateBody } from '../generated/api.zod'
```

**Path rules:**

- Core: `~/generated/core/...` (tilde prefix)
- Products from outside: `products/<product>/frontend/generated/...` (no tilde)
- Products from inside: relative `../generated/...` or `./generated/...`

Use `import type` for types to enable proper tree-shaking.

## How generated functions work under the hood

Generated functions wrap the same `api` module via `api-orval-mutator.ts`:

```text
surveysList(projectId, params)
  → apiMutator(url, { method: 'GET' })
    → api.get(url)
```

Switching to generated functions does not change HTTP behavior — same cookies, same CSRF, same error handling. The only difference is type safety and URL construction.

## Verifying the migration

1. **TypeScript check:** `pnpm --filter=@posthog/frontend typescript:check`
2. **Grep for leftover manual types:** search for the old type name across the codebase
3. **Run relevant tests:** `hogli test <test_file>`

## Related

- **Backend side:** use `improving-drf-endpoints` to fix serializers that produce poor types
- **Type system docs:** `docs/published/handbook/engineering/type-system.md`
- **API mutator:** `frontend/src/lib/api-orval-mutator.ts`
- **Regenerate types:** `hogli build:openapi`
