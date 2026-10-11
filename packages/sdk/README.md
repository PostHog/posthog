# @posthog/sdk

A TypeScript client for agents that call the PostHog API. It shares operation definitions, descriptions, and response projections with the MCP codegen pipeline. It runs on Node.js 22 or later.

```sh
npm install @posthog/sdk
export POSTHOG_PERSONAL_API_KEY=phx_example
export POSTHOG_PROJECT_ID=123
```

```ts
import { client } from '@posthog/sdk'
import type { FeatureFlagsListInput, FeatureFlagsListOutput } from '@posthog/sdk/feature-flags'

const input: FeatureFlagsListInput = { search: 'checkout', limit: 10 }
const output: FeatureFlagsListOutput = await client.featureFlags.list(input)
console.log(output.data.results)
```

`client` is also the default export. Importing it does not read credentials or make requests. Configuration is read on first use and retained for that client.

## Discover methods without credentials

```sh
npx --no-install posthog-sdk list
npx --no-install posthog-sdk search "archive feature flag"
npx --no-install posthog-sdk describe featureFlags.archive
npx --no-install posthog-sdk describe queries.trends --json
rg 'interface FeatureFlagsArchive' node_modules/@posthog/sdk/src
```

`describe` prints the method description and TypeScript contracts, including nested types. Its JSON output gives the source and declaration paths, required scopes, MCP tool name, and documentation provenance. Both the original schema comments and MCP overrides are retained in the shipped `.ts` and `.d.ts` files. Object contracts are named interfaces; enums and discriminated unions use named type aliases.

```ts
import { catalog, searchTools, describeTool } from '@posthog/sdk/discovery'

const matches = searchTools('retention', { limit: 5 })
const method = describeTool(matches[0]!.method)
console.log(method?.input.source, method?.output.declaration)
```

The package includes `catalog.json`, per-method `catalog/` files, and an `AGENTS.md` entry point. Discovery is local and does not load the API runtime. Agents must be told the package is available or discover it through the project's dependencies; npm does not automatically register its methods as MCP tools.

## Configuration and project selection

```ts
import { createPostHogClient } from '@posthog/sdk'

const api = createPostHogClient({
  token: 'phx_example',
  baseUrl: 'https://eu.posthog.com',
  projectId: 123,
  env: false,
})

const context = await api.context()
const otherProject = api.project(456)
const flags = await otherProject.featureFlags.list({})
```

| Option          | Environment default                                | Fallback                  |
| --------------- | -------------------------------------------------- | ------------------------- |
| `token`         | `POSTHOG_PERSONAL_API_KEY`, then `POSTHOG_API_KEY` | Required in token mode    |
| `baseUrl`       | `POSTHOG_API_URL`, then `POSTHOG_HOST`             | `https://us.posthog.com`  |
| `projectId`     | `POSTHOG_PROJECT_ID`                               | Credential/user discovery |
| `authMode`      | `POSTHOG_AUTH_MODE`                                | `token`                   |
| `publicBaseUrl` | `POSTHOG_PUBLIC_URL`                               | API URL in token mode     |
| `timeoutMs`     | None                                               | 30,000                    |

Explicit options take precedence. `env: false` disables environment defaults. Use a personal API key or OAuth access token; an ingestion key (`phc_…`) cannot authorize management API calls.

Project selection prefers `client.project(id)`, then `projectId`, then `POSTHOG_PROJECT_ID`. Without these, the client reads the token's scope. A single scoped project is selected directly; otherwise the user's selected project is used only if the credential permits it. This lookup needs `user:read`. Ambiguous or unavailable selection produces a `PostHogError` with candidate project IDs instead of choosing the first project. `tokenType` can identify credentials without the usual `phx_` or `pha_` prefix.

The selected project is retained by the client until an explicit context switch. A client created with `client.project(id)` has an immutable project scope. Scoping a second client does not update the user's PostHog settings. API authorization failures do not trigger a project switch.

## Tasks and proxies that supply auth

A Tasks environment can supply these defaults so the same exported `client` works without a local token:

```sh
export POSTHOG_AUTH_MODE=proxy
export POSTHOG_API_URL=https://proxy.example.com/task/posthog
export POSTHOG_PUBLIC_URL=https://us.posthog.com
export POSTHOG_PROJECT_ID=123
```

Requests preserve the proxy's path prefix and omit the `Authorization` header. Environment tokens are ignored in proxy mode. The proxy supplies authentication; the project comes from an explicit option or the environment because the client cannot introspect a credential it does not hold. Public resource links use `POSTHOG_PUBLIC_URL`.

The same settings are available as client options. An injected `fetch` can integrate a host-provided transport. These options define the proxy integration contract; this package does not create or deploy a Tasks proxy.

## Queries and errors

```ts
const output = await client.queries.trends({
  series: [{ kind: 'EventsNode', event: '$pageview' }],
  dateRange: { date_from: '-7d' },
})

if (output.data.state === 'complete') console.log(output.data.result.results)
if (output.data.state === 'pending') console.log(output.data.queryStatus.id)
if (output.data.state === 'failed') console.error(output.data.error)
```

Omitting `filterTestAccounts` reads the project setting. Supply it explicitly when the credential cannot read project settings. Queries preserve structured results and warnings; they do not apply MCP text formatting or truncation. Pending queries are returned without automatic polling. A pending result includes the query ID for callers that manage polling through the API.

`queries.sql({ query: 'SELECT 1' })` returns column/type metadata and JSON-valued results. SQL determines its row shape at runtime. Some analytics response schemas also leave series fields unspecified; those gaps are documented as JSON values rather than asserted row types. Optional query response fields also allow `null`, matching the backend's model serialization.

Each method validates its input before calling the API. Shared MCP handlers retain their validation, aliases, hooks, projections, links, and agent notes. Responses use the generated TypeScript interfaces without runtime schema validation. PATCH requests preserve omitted fields.

```ts
import { PostHogError } from '@posthog/sdk'

try {
  await client.featureFlags.archive({ id: 456 }, { signal: AbortSignal.timeout(5_000) })
} catch (error) {
  if (error instanceof PostHogError) console.error(error.details.kind, error.details.status)
  else throw error
}
```

Errors carry a typed kind, API status, request ID, and retry-after information when available. Tool refusals throw `PostHogError` with kind `tool`; they never masquerade as successful data. The deadline covers project discovery and all API calls made by a tool. Shared MCP handlers retain their bounded retries for safe reads and rate limits. Structured query and REST adapters do not retry. Redirects are rejected so credentials are not forwarded to another route.

## Stateful and host tools

All tools are discoverable regardless of the current credential. The API checks access on each request. Methods that send data to an LLM also check the selected organization's AI-processing consent.

`switch-project` and `switch-organization` change context only for the client instance. They do not change the user's PostHog settings or another client. A client returned by `client.project(id)` keeps its immutable project scope.
Set `organizationId` or `POSTHOG_ORGANIZATION_ID` for organization operations, or let the client derive it from the selected project.

Confirmed actions retain MCP's separate prepare and execute methods. Show the prepare result to the user, wait for their literal `confirm`, and pass it with the returned `confirmation_hash` to the matching execute method. Confirmation tokens expire after 15 minutes, are bound to their action and scope, and can be consumed once. Prepare and execute must use the same client instance in the same process; the SDK keeps signing keys and pending payloads in that client's memory.

Task artifact and comment tools use `taskId` or `POSTHOG_TASK_ID`. The API validates that task against the credential. To use `agent-feedback`, provide a `feedback` callback to `createPostHogClient`; this is the SDK host's feedback sink. The SDK reports a configuration error if the callback is missing and surfaces callback failures. Successful delivery means the callback completed; it does not imply the PostHog team received the feedback.

MCP UI tools return their structured payloads; the SDK does not run an MCP UI renderer. Trace query tools preserve MCP's redaction and compaction behavior.

## Coverage and development

Every tool in MCP's registered catalog has an SDK method, including handwritten tools, embedded query wrappers, deprecated aliases, and both halves of confirmed actions. `coverage.json` maps each MCP name to its SDK method. Generation fails if the SDK and MCP catalogs differ. Disabled MCP definitions are not part of either catalog.

From the repository root:

```sh
hogli build:openapi-sdk
pnpm --filter=@posthog/sdk build
pnpm --filter=@posthog/sdk test
pnpm --filter=@posthog/sdk check:package
```

Generation reads `frontend/tmp/openapi.json` (or `OPENAPI_SCHEMA_PATH`), `frontend/src/queries/schema.json`, and MCP's registered factories. `hogli build:openapi` builds the backend schema and MCP artifacts before generating the SDK. An optional `sdk: { namespace: featureFlags, method: archive }` customizes naming; it does not control inclusion. Other methods use the definition's module as namespace and the camel-cased MCP tool name as method name.

Input interfaces come from the actual MCP validators. Output interfaces come from handler result types, API schemas, and query adapters. Union inputs have named interface variants. The package retains original comments, field overrides, and tool descriptions. Source contracts that leave a value unspecified are labeled as JSON rather than given invented fields.

The SDK bundles MCP handlers with a local host that supplies the direct HTTP transport, client context, and confirmation state. It does not open an MCP connection or require an MCP server, Redis, or Cloudflare. The generator replaces server-only UI registration and telemetry with SDK host behavior. Agent feedback is delivered only to the configured callback.

Change the schema, MCP definition, or adapter and regenerate; do not edit `src/generated/` or `catalog/` by hand. The packed-package check installs a tarball into a separate project, verifies offline discovery, executes a mocked request, and compiles a strict TypeScript consumer. Publishing is a separate release step.

## Reusable scout jobs

[Scout job examples](../../products/signals/scripts/scout-jobs/jobs.ts) collect evidence through the SDK and return one JSON result for a scout to interpret. They are read-only and do not emit reports, change memory, or modify scout configuration. The example package links this checkout's built SDK; run its build first. The scripts import `@posthog/sdk`, so they can also run outside the checkout with that package installed. Running the TypeScript entry point requires Node.js with type stripping, such as Node.js 24.

| Job         | Work it handles                                                                                                                     | What the scout still decides                                                                              |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `context`   | Collects the profile summary, recent runs, steering notes, matching memory, and follow-ups concurrently.                            | Which product data to investigate; read the pinned skill and full inventory separately when needed.       |
| `errors`    | Selects active errors by occurrence count and fetches each selected issue's equal-duration window seven days earlier.               | Whether counts indicate a regression after accounting for traffic, users, releases, and existing reports. |
| `followups` | Collects report snapshots, check state, artifact previews, and matching memory for explicit reports or the newest resolved reports. | Whether a fix is measurable, whether its outcome is confirmed, and whether to create or update a check.   |
| `audit`     | Pages through a fixed run window and counts execution outcomes, report creation, and report edits independently.                    | Whether a scout's output is useful; output counts are not quality or cost measurements.                   |

From the repository root, after configuring credentials as above:

```sh
npm install --prefix products/signals/scripts/scout-jobs --ignore-scripts --package-lock=false --workspaces=false
node --experimental-strip-types products/signals/scripts/scout-jobs/run.ts context --project-id 123 --skill signals-scout-error-tracking --memory error_tracking
node --experimental-strip-types products/signals/scripts/scout-jobs/run.ts errors --project-id 123 --hours 24 --limit 5
node --experimental-strip-types products/signals/scripts/scout-jobs/run.ts followups --project-id 123 --limit 5
node --experimental-strip-types products/signals/scripts/scout-jobs/run.ts audit --project-id 123 --from 2026-01-01T00:00:00Z --to 2026-01-08T00:00:00Z
node --experimental-strip-types --test products/signals/scripts/scout-jobs/jobs.test.ts
```

`context` accepts `--run-id` to read that scout run's emit eligibility and `--limit` to bound each list. Its context is intentionally a sample, not the complete memory or run history. `followups --report-id <uuid>` targets a report; repeat the option for several reports. Its artifact and summary previews carry truncation markers and artifact IDs for fetching full evidence later. `errors` reports missing baselines explicitly and does not treat absence from a ranked list as zero. An occurrence ratio is not a traffic-normalized error rate.

Results identify the project and collection time. Failed sections retain their errors and produce `status: "partial"` with exit code 2. Authentication or top-level request failures exit nonzero. The audit also reports partial coverage when `--max-pages` is reached or a full page ends with tied timestamps that the timestamp-only cursor cannot safely traverse. It uses `created_at` for pagination and counts `emitted_report_ids` and `edited_report_ids` even when the legacy `emitted_count` is zero.

The credential needs the scopes of each selected operation. In particular, the current report-check list endpoint requires `signal_scout_report:write` even for its read request; without it, `followups` returns the other evidence with an unknown check queue and a visible permission error. The scripts do not obtain broader credentials. To use these jobs in scheduled scouts, install the SDK and the chosen script in the sandbox, expose the scoped task credentials or authenticated proxy, and point the skill at the entry point. This PR does not provision that runtime integration.
