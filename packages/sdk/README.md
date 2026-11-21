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

## Development

From the monorepo root, run `hogli build:openapi-sdk` after generating the MCP tools and OpenAPI schema. Run `pnpm --filter=@posthog/sdk build`, `pnpm --filter=@posthog/sdk test`, and `pnpm --filter=@posthog/sdk check:package` to verify the package and a strict TypeScript consumer.
