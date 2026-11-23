# PostHog SDK

Use `@posthog/sdk` from a Node.js 22.19+ application to call PostHog tools with named TypeScript inputs and results. The package includes the tool runtime used by `hog api`. Its installed version pins the tool implementations and TypeScript definitions together.

```typescript
import { createPostHogClient } from '@posthog/sdk'

const posthog = createPostHogClient({ projectId: 23 })
const page = await posthog.featureFlags.list({ limit: 10 })
for (const flag of page.results) {
  console.log(flag.key)
}
```

Import `{ client }` for environment configuration. Set `POSTHOG_PERSONAL_API_KEY` or `POSTHOG_API_KEY`, and `POSTHOG_API_URL` for your region or self-hosted instance. Set `POSTHOG_PROJECT_ID` to select a starting project. Use `client.project(id)` to pin an independent client to one project. Without an explicit project, the SDK resolves a permitted project from the credential and current user. Discovery itself works offline and needs no credential.

Run `posthog-sdk --agent-help` to locate the installed method index and API reference. The `@posthog/sdk/discovery` export lists the available method names, corresponding MCP tools, scopes, and availability conditions. Your credentials, the instance and the shared tool catalog determine which calls can run.

Successful calls return the tool's JSON value. A failed call throws `PostHogError` with details about the failure. Pass `{ signal, timeoutMs }` as the second argument to control an individual call. A destructive call requires an explicit `{ confirm: true }` after you verify the intended action. For a prepare/execute pair, retain the client that prepared the action, show the confirmation prompt to the user, then supply their response and the signed value to execute. A confirmation expires and can be used once.

In a Tasks sandbox, set `authMode: 'proxy'`, `baseUrl` to the proxy endpoint, `publicBaseUrl` to the instance used for PostHog links, and `projectId` to the active project. The proxy supplies the credential. Calls keep its URL prefix and omit the authorization header. You can pass a custom `fetch` for your host or for tests.

## Definitions in code

`@posthog/sdk/define` declares PostHog entities as values, for a stack folder that `hog check` evaluates. The first argument is the definition's key, its identity in the stack. For kinds with a natural key (an event name, a flag key, a model or endpoint name, a metric name, a context page path) the key is that natural key. The body is the entity's create body, and a field that takes another entity's ID takes its definition instead.

```typescript
import { dashboard, event, model, prop, sql, trend } from '@posthog/sdk/define'

export const checkout = event('checkout_completed', {
  enforcement: 'reject',
  properties: {
    account_id: prop.string().required(),
    total_usd: prop.number().required(),
    plan: prop.enum(['free', 'team']),
  },
})

export const mrr = model('mrr', {
  columns: { account_id: 'string', month: 'date', mrr_usd: 'number' },
  query: sql`
    select ${checkout.props.account_id} as account_id, toStartOfMonth(timestamp) as month, sum(${checkout.props.total_usd}) as mrr_usd
    from events where event = ${checkout} group by account_id, month`,
})

export const revenue = dashboard('revenue', {
  name: 'Revenue',
  tiles: [trend(mrr, { sum: 'mrr_usd', interval: 'month' }), trend(checkout, { where: { plan: 'team' } })],
})
```

The kinds are `insight`, `dashboard`, `alert`, `destination`, `flag`, `cohort`, `action`, `event` with `prop` (which also makes a `propertyGroup`), `model`, `endpoint`, `source`, `metric`, `check`, `contextPage` (and `contextPages(folder)` for a folder of `.md` files), `experiment` and `survey`. `trend`, `funnel` and `hogql` build insight bodies, `tile` and `text` build dashboard tiles, `sql` builds a HogQL query, `file('./x.sql')` reads a file next to the calling one, and `secret('NAME')` names a credential PostHog holds. In `sql`, an event becomes its name as a string literal and `event.props.x` becomes `properties.x`. An inline tile insight gets the key `<dashboard key>-<tile key>`, from `tile(insight, { key })` or a slug of its name, so reordering tiles keeps it.

`typed<typeof defs>()(posthog)` gives a client with the same members as `posthog`, except that `capture` takes only declared events with their declared properties, `variant` returns a flag's declared variants, and `captureRaw` takes anything. Import the definitions with `import type`, so none of them reach a browser bundle. `RowsOf<typeof model>` and `DimensionsOf<typeof metric>` type a model's rows and a metric's dimensions.

`@posthog/sdk/stack` evaluates and checks a folder:

- `loadStack(dir, { validator })` imports the folder's `index.ts` and returns the sorted description and a list of problems, each with a stable `code`. Pass `createApiToolLibrary()` from the MCP CLI library as the validator, or `{ skipSchemas: true }` to check keys, references and rules only. The folder's modules load into the calling process once, so a process that checks a folder again after it changed must start fresh.
- `typeCheckStack(dir)` type-checks the folder with the project's own TypeScript compiler, and reports `skipped` with a reason when the project has none.
- `generateDefinitions(resources)` writes definitions that evaluate back to those resources, one file per family of kinds plus `index.ts`.
- `foldDrift(dir, drift)` writes a drifted value into the definition where the file holds it as a literal, and returns the other fields for a person or agent to change.

## Development

From the monorepo root, run `hogli build:openapi-sdk` after generating the MCP tools and OpenAPI schema. Run `pnpm --filter=@posthog/sdk build`, `pnpm --filter=@posthog/sdk test`, and `pnpm --filter=@posthog/sdk check:package` to verify the package and a strict TypeScript consumer.
