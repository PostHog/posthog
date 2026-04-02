# Type compatibility — generated vs handwritten

## readonly fields

Generated types mark fields that are `read_only=True` in the serializer as `readonly`:

```typescript
// Generated
interface DashboardApi {
  readonly id: number
  readonly created_at: string
  name: string // writable
}

// Handwritten (typical)
interface DashboardType {
  id: number
  created_at: string
  name: string
}
```

This means code that mutates response objects directly will error:

```typescript
// Error: Cannot assign to 'id' because it is a read-only property
dashboard.id = 123
```

**Fix options:**

1. Stop mutating the response — spread into a new object: `const local = { ...dashboard, id: 123 }`
2. If building a request body, use the `Patched*Api` type or derive the parameter type via `Parameters<typeof fooCreate>[1]`

## Patched types for partial updates

Generated types include `Patched*Api` variants where all fields are optional — matching PATCH semantics:

```typescript
interface PatchedDashboardApi {
  readonly id?: number
  name?: string
  description?: string
}
```

Use `PatchedFooApi` when building partial update payloads.

## Pagination wrappers

Generated pagination types follow this pattern:

```typescript
interface PaginatedDashboardListApi {
  count: number
  next?: string | null
  previous?: string | null
  results: DashboardApi[]
}
```

This replaces the generic `PaginatedResponse<T>` from handwritten types. The shape is identical, so usage code doesn't need to change — only the type annotation.

## Nullable vs optional

Generated types distinguish between:

- **`nullable`** — field can be `null` (`field: string | null`)
- **`optional`** — field can be omitted (`field?: string`)
- **Both** — `field?: string | null`

Handwritten types often use `?` for both cases. When migrating, you may see TypeScript errors where code checks `if (field)` but the generated type says the field is always present (just possibly `null`). Adjust the check:

```typescript
// Before (handwritten type had field?: string)
if (response.verified_at) { ... }

// After (generated type has verified_at: string | null)
if (response.verified_at) { ... }  // still works — null is falsy
```

## Enum types

Generated enums use `as const` objects:

```typescript
export type SurveyTypeApi = (typeof SurveyTypeApi)[keyof typeof SurveyTypeApi]
export const SurveyTypeApi = {
  Popover: 'popover',
  Widget: 'widget',
  FullScreen: 'full_screen',
} as const
```

Handwritten enums might use TypeScript `enum` or string unions. When migrating:

```typescript
// Before
if (survey.type === 'popover') { ... }

// After — both work, but the const object gives autocomplete
if (survey.type === SurveyTypeApi.Popover) { ... }
if (survey.type === 'popover') { ... }  // also fine
```

## Fields present in handwritten but not generated

If a handwritten type has fields that don't appear in the generated type, the serializer doesn't expose them. Common causes:

- Field was removed from the serializer
- Field is computed client-side (never came from the API)
- Field is from a different endpoint (e.g., a detail view vs. list view serializer)

For client-side computed fields, extend the generated type:

```typescript
import type { DashboardApi } from 'products/dashboards/frontend/generated/api.schemas'

interface DashboardWithLocal extends DashboardApi {
  _localDraft: boolean // client-only field
}
```

## Fields present in generated but not handwritten

The serializer may expose fields the handwritten type never included. This is fine — the generated type is the source of truth. Frontend code may start using the new fields.

## Request body types

Generated create/update functions accept a `NonReadonly<T>` parameter internally — this is a non-exported utility type that strips `readonly`. You don't need to import or reference it directly. Just pass a plain object and TypeScript will accept it:

```typescript
// This works — plain objects are writable
await domainsCreate(orgId, { domain: 'example.com' })
```

If you need to explicitly type a request body variable, derive the type from the function signature:

```typescript
type CreateBody = Parameters<typeof domainsCreate>[1]
const body: CreateBody = { domain: 'example.com' }
```
