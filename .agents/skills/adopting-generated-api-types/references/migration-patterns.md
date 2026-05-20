# Migration patterns — before/after

## High-level object API

### 1. Entity get

```typescript
// Before
import api from 'lib/api'
import { Survey } from '~/types'

const survey = await api.surveys.get(surveyId)

// After
import { surveysRetrieve } from 'products/surveys/frontend/generated/api'

const survey = await surveysRetrieve(String(values.currentProjectId), surveyId)
```

Generated functions always take `projectId` as the first argument — the high-level API pulls it from context implicitly, but generated functions are explicit.

### 2. Entity list

```typescript
// Before
const surveys = await api.surveys.list({ limit: 100 })

// After
import { surveysList } from 'products/surveys/frontend/generated/api'

const surveys = await surveysList(String(values.currentProjectId), { limit: 100 })
```

### 3. Entity create

```typescript
// Before
const survey = await api.surveys.create(surveyPayload)

// After
import { surveysCreate } from 'products/surveys/frontend/generated/api'

const survey = await surveysCreate(String(values.currentProjectId), surveyPayload)
```

### 4. Entity update

```typescript
// Before
const updated = await api.surveys.update(surveyId, surveyPayload)

// After
import { surveysPartialUpdate } from 'products/surveys/frontend/generated/api'

const updated = await surveysPartialUpdate(String(values.currentProjectId), surveyId, surveyPayload)
```

### 5. Entity delete

```typescript
// Before
await api.surveys.delete(surveyId)

// After
import { surveysDestroy } from 'products/surveys/frontend/generated/api'

await surveysDestroy(String(values.currentProjectId), surveyId)
```

## Raw HTTP methods

### 6. GET with type parameter

```typescript
// Before
import api from 'lib/api'
import { OrganizationDomainType } from '~/types'

const domain = await api.get<OrganizationDomainType>(`api/organizations/${orgId}/domains/${domainId}/`)

// After
import { domainsRetrieve } from '~/generated/core/api'

const domain = await domainsRetrieve(orgId, domainId)
```

### 7. Paginated GET

```typescript
// Before
import { PaginatedResponse, OrganizationInviteType } from '~/types'

const invites = await api.get<PaginatedResponse<OrganizationInviteType>>(
  `api/organizations/${orgId}/invites/?limit=100`
)
const items = invites.results

// After
import { invitesList } from '~/generated/core/api'

const invites = await invitesList(orgId, { limit: 100 })
const items = invites.results // typed as OrganizationInviteApi[]
```

Query parameters are passed as an argument object — no manual URL encoding.

### 8. POST (create)

```typescript
// Before
const domain = await api.create<OrganizationDomainType>(`api/organizations/${orgId}/domains/`, {
  domain: 'example.com',
})

// After
import { domainsCreate } from '~/generated/core/api'

const domain = await domainsCreate(orgId, { domain: 'example.com' })
```

The request body type is `NonReadonly<OrganizationDomainApi>` — read-only fields like `id` are stripped automatically.

### 9. PATCH (partial update)

```typescript
// Before
const updated = await api.update<OrganizationDomainType>(`api/organizations/${orgId}/domains/${domainId}/`, {
  jit_provisioning_enabled: true,
})

// After
import { domainsPartialUpdate } from '~/generated/core/api'

const updated = await domainsPartialUpdate(orgId, domainId, {
  jit_provisioning_enabled: true,
})
```

### 10. DELETE

```typescript
// Before
await api.delete(`api/organizations/${orgId}/domains/${domainId}/`)

// After
import { domainsDestroy } from '~/generated/core/api'

await domainsDestroy(orgId, domainId)
```

## ApiRequest builder

### 11. Builder to generated function

```typescript
// Before
import { ApiRequest } from 'lib/api'

const url = new ApiRequest().projects().projectsDetail(projectId).surveys().assembleFullUrl()
const surveys = await api.get<PaginatedResponse<Survey>>(url)

// After
import { surveysList } from 'products/surveys/frontend/generated/api'

const surveys = await surveysList(String(projectId))
```

### 12. Builder with action

```typescript
// Before
await new ApiRequest()
  .survey(surveyId)
  .withAction('summarize_responses')
  .withQueryString({ question_index: 1 })
  .create({ data: { force_refresh: true } })

// After — if the @action has @extend_schema, a generated function exists:
import { surveysSummarizeResponsesCreate } from 'products/surveys/frontend/generated/api'

await surveysSummarizeResponsesCreate(String(projectId), String(surveyId), {
  force_refresh: true,
})

// If no generated function exists, keep the builder and fix the backend first.
```

## Kea patterns

### 13. Kea logic loader

```typescript
// Before
loaders({
  domains: [
    [] as OrganizationDomainType[],
    {
      loadDomains: async () => {
        const response = await api.get<PaginatedResponse<OrganizationDomainType>>(
          `api/organizations/${values.currentOrganizationId}/domains/`
        )
        return response.results
      },
    },
  ],
})

// After
import { domainsList } from '~/generated/core/api'
import type { OrganizationDomainApi } from '~/generated/core/api.schemas'

loaders({
  domains: [
    [] as OrganizationDomainApi[],
    {
      loadDomains: async () => {
        const response = await domainsList(values.currentOrganizationId)
        return response.results
      },
    },
  ],
})
```

### 14. Kea listener with error handling

```typescript
// Before
listeners({
  saveDomain: async ({ domain }) => {
    try {
      const response = await api.update<OrganizationDomainType>(
        `api/organizations/${orgId}/domains/${domain.id}/`,
        domain
      )
      actions.saveDomainSuccess(response)
    } catch (e) {
      actions.saveDomainFailure(String(e))
    }
  },
})

// After
import { domainsPartialUpdate } from '~/generated/core/api'

listeners({
  saveDomain: async ({ domain }) => {
    try {
      const response = await domainsPartialUpdate(orgId, domain.id, domain)
      actions.saveDomainSuccess(response)
    } catch (e) {
      actions.saveDomainFailure(String(e))
    }
  },
})
```

Error handling stays the same — `apiMutator` throws `ApiError` just like `api.update` does.

## Edge cases

### 15. Call with abort signal

```typescript
// Before
const controller = new AbortController()
const result = await api.get<MyType>(url, { signal: controller.signal })

// After
const controller = new AbortController()
const result = await myEndpointRetrieve(id, undefined, { signal: controller.signal })
```

The last argument to generated functions is `options?: RequestInit` — pass `signal`, `headers`, etc. there.

### 16. Mixed file — partial migration

When a file has many manual calls and you're only touching some:

```typescript
// OK to migrate incrementally — mix generated and manual calls in the same file
import api from 'lib/api' // keep for un-migrated calls
import { domainsList, domainsCreate } from '~/generated/core/api' // migrated
import type { OrganizationDomainApi } from '~/generated/core/api.schemas'

// Migrated
const domains = await domainsList(orgId)

// Not yet migrated (no generated function for this custom action)
const verification = await api.create(`api/organizations/${orgId}/domains/${id}/verify/`)
```

Don't force-migrate calls where no generated function exists — leave them and fix the backend endpoint first.

### 17. Custom methods without generated equivalents

High-level API methods like `api.surveys.getResponsesCount()` or `api.dashboards.streamTiles()` may not have generated equivalents if the backend `@action` lacks `@extend_schema`. Leave these in place and file a follow-up to annotate the backend endpoint.

```typescript
// Keep as-is until the backend @action is annotated
const counts = await api.surveys.getResponsesCount(surveyIds)
```
