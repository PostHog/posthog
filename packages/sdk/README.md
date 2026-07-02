# @posthog/sdk

TypeScript SDK for the **PostHog management API** — feature flags, insights, dashboards, experiments, cohorts, surveys, queries, and more.

This is the _management API_ SDK (create/read/update resources).
It is **not** an event-capture library — for sending events use [`posthog-js`](https://posthog.com/docs/libraries/js) (browser) or [`posthog-node`](https://posthog.com/docs/libraries/node) (server).

Isomorphic (browser, Node, workers, sandboxes): fetch-based, no Node-only dependencies, injectable `fetch`.

## Install

```bash
pnpm add @posthog/sdk
```

## Initialize

### From environment variables (default client)

```ts
import { client } from '@posthog/sdk'

// Reads these on first method call (never at import time):
//   POSTHOG_API_KEY          (required)
//   POSTHOG_HOST             (default: https://us.posthog.com)
//   POSTHOG_PROJECT_ID       (optional — else resolved from /api/users/@me/)
//   POSTHOG_ORGANIZATION_ID  (optional — else resolved from /api/users/@me/)
await client.featureFlags.list()
```

Importing the package never touches `process` and never throws (safe in the browser).
A missing key throws a `MissingApiKeyError` naming the env vars the first time you call a method.

### Explicit configuration

```ts
import { createClient } from '@posthog/sdk'

const ph = createClient({
  apiKey: 'phx_…',
  host: 'https://eu.posthog.com', // default: https://us.posthog.com
  projectId: 123, // optional; lazily resolved from /api/users/@me/ if omitted
  organizationId: 'org_…', // optional; lazily resolved likewise
  fetch: customFetch, // optional transport override (proxies, tests, sandboxes)
  headers: { 'X-Trace': 'abc' }, // optional default headers
})
```

Accepted credentials: personal API keys (`phx_`), project secret keys (`phs_`) where supported, and any bearer token — the SDK just sends `Authorization: Bearer <key>`.

## Example calls

```ts
// List / read / create / update / soft-delete feature flags
const flags = await client.featureFlags.list({ active: 'true' })
const flag = await client.featureFlags.get({ id: 42 })
const created = await client.featureFlags.create({ key: 'beta', name: 'Beta gate' })
await client.featureFlags.update({ id: created.id, active: true })
await client.featureFlags.delete({ id: created.id })

// Other resources
const dashboard = await client.dashboards.get({ id: 7 })
const org = await client.organization.get({ id: 'org_abc' })

// Insight queries (POST /api/environments/{projectId}/query/) — the query `kind` is injected
const trends = await client.query.trends({ series: [{ event: '$pageview' }] })
const funnel = await client.query.funnel({ series: [{ event: 'signup' }, { event: 'activate' }] })
// Actors drill-down — the insight query is wrapped in an ActorsQuery automatically
const actors = await client.query.trendsActors({ source: { kind: 'TrendsQuery', series: [] }, day: '2024-01-15' })
// Escape hatch for any query node the API accepts (sent verbatim)
const rows = await client.query.run({ query: { kind: 'HogQLQuery', query: 'select count() from events' } })

// Per-call overrides: projectId / organizationId / signal / headers
await client.insights.list({}, { projectId: 999, signal: controller.signal })
```

`project_id` / `organization_id` path segments are auto-resolved from configuration (or `/api/users/@me/`) and can be overridden per call via the trailing `opts` argument. Responses are the **raw, unfiltered** PostHog API payloads.

### Errors

Typed errors are thrown for non-2xx responses: `PostHogApiError` (carries `status`), `PostHogPermissionError` (carries `missingScope`), `PostHogValidationError` (carries `attr`/`extra`), and `PostHogRateLimitError` (429 after the retry budget is exhausted). 429s are retried automatically with `Retry-After` / jittered backoff.

## What's generated, and how to regenerate

The transport core (`src/core/`) is handwritten. The resource layer (`src/generated/`) is emitted by `scripts/generate.ts` from the **committed** PostHog MCP codegen artifacts:

| Output                                      | Derived from                                                                                            |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `src/generated/resources/*.ts`, `client.ts` | `services/mcp/src/tools/generated/*.ts` (parsed handlers: method, path, body/query, scope, soft-delete) |
| `src/generated/inputs.ts` (request types)   | `services/mcp/src/generated/<module>/api.ts` (Orval Zod schemas → JSON Schema → plain TS)               |
| `src/generated/schemas.ts` (response types) | `services/mcp/src/api/generated.ts` (the `Schemas` namespace)                                           |

Because those artifacts are produced by `hogli build:openapi`, the SDK regenerates downstream of them:

```bash
hogli build:openapi                      # regenerates the whole chain, incl. the SDK
# or just the SDK, from already-committed artifacts:
pnpm --filter=@posthog/sdk run generate
```

Generated output is committed. Don't edit it by hand — change the Django serializers / MCP YAML and regenerate.

> **No runtime Zod.** Input types are materialized to plain TypeScript at generate time, so nothing in the shipped bundle imports Zod. Zod is a build-time devDependency only.

### Coverage

Every MCP tool becomes an SDK method, through one of two emitter paths: standard single-request handlers are parsed directly, and the `query-*` insight/actors wrapper tools are emitted onto `client.query.*` backed by the handwritten wrapper runtime in `src/core/query.ts` (kind injection, ActorsQuery wrapping, retention interval projection). `client.query.run({ query })` remains available for query kinds without a dedicated method.

## Scripts

```bash
pnpm --filter=@posthog/sdk run generate    # regenerate the resource layer
pnpm --filter=@posthog/sdk run build       # dual ESM/CJS + .d.ts (tsup)
pnpm --filter=@posthog/sdk run typecheck   # tsc --noEmit
pnpm --filter=@posthog/sdk run test        # vitest (msw-backed)
```

## Status

`0.x` — the generated surface may change as the underlying API and MCP definitions evolve.
