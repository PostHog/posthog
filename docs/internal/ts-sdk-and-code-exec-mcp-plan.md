# Plan: `@posthog/sdk` (TypeScript) on the MCP codegen pipeline + code-execution MCP

Status: proposal.
Owner: Max AI / MCP.

Two deliverables:

1. A generated TypeScript SDK (`@posthog/sdk`) built from the same OpenAPI → Orval → codegen pipeline that powers the MCP server, usable in generated artifacts (React/frontend/backend apps), the CLI, and sandboxed agent scripts.
2. A high-level design for evolving the MCP server toward code execution ("Cloudflare code mode"): agents write TypeScript against `@posthog/sdk` and the server runs it in a sandbox, instead of issuing dozens of individual tool calls.

---

## 1. The codegen pipeline today (research summary)

`hogli build:openapi` (defined in `hogli.yaml`) is the umbrella. The steps that matter here:

```text
build:openapi-schema      python manage.py spectacular → frontend/tmp/openapi.json
                          (DEBUG=1 OPENAPI_INCLUDE_INTERNAL=1, --fail-on-warn; drf-spectacular
                          config in posthog/settings/web.py SPECTACULAR_SETTINGS)
build:openapi-types       frontend/bin/generate-openapi-types.mjs → per-product Orval output:
                          api.ts (fetch client via lib/api mutator), api.schemas.ts (types),
                          api.zod.ts. Routed by x-product → products/*/frontend/generated/
                          or frontend/src/generated/core/
build:openapi-mcp-types   services/mcp/scripts/generate-mcp-types.mjs → full-spec types wrapped
                          in `namespace Schemas` (services/mcp/src/api/generated.ts)
build:openapi-mcp         services/mcp/scripts/generate-orval-schemas.mjs → per-domain Zod
                          schemas (services/mcp/src/generated/<module>/api.ts), filtered to the
                          operations enabled in YAML definitions
build:openapi-mcp-tools   services/mcp/scripts/generate-tools.ts → typed MCP tool handlers
                          (services/mcp/src/tools/generated/*.ts) from
                          products/*/mcp/*.yaml + Orval Zod schemas
```

Shared machinery:

- `tools/openapi-codegen` (`@posthog/openapi-codegen`, workspace package): schema filtering (`filterSchemaByOperationIds`), preprocessing, parallel in-process Orval runs, Zod post-processing. Already consumed by both the frontend generator and the MCP generator.
- `products/<product>/mcp/*.yaml` (validated by `services/mcp/scripts/yaml-config-schema.ts`): the curated configuration layer — which operations are exposed, scopes, LLM-facing descriptions, param overrides, response field filtering, `soft_delete`, `confirmed_action`, etc. `scaffold-yaml --sync-all` keeps it in sync with the spec (CI drift check).
- Generated handlers all bottom out in one primitive: `context.api.request<T>({ method, path, body, query })` on `ApiClient` (`services/mcp/src/api/client.ts`) — fetch-based, `Authorization: Bearer <token>`, typed errors (`PostHogApiError`, `PostHogPermissionError` with missing-scope parsing, `PostHogValidationError`), 429 retry with backoff.

Adjacent facts that shape the plan:

- `services/mcp` is **not** published to npm; it ships as a Cloudflare Worker (edge OAuth/router) + Hono runtime on k8s (`cd-mcp-image.yml`).
- The MCP already has a progressive-disclosure `exec` tool (`services/mcp/src/tools/exec.ts`): one registered tool with `tools | search | info | schema | call` verbs. The TypeScript CLI (`posthog-cli api …`) embeds the same dispatcher, is bundled with esbuild, and is vendored into the Rust `posthog-cli` (`cli/build.rs` inlines `lib/posthog-api-cli.mjs`). Its env conventions: `POSTHOG_API_KEY`, `POSTHOG_HOST`, `POSTHOG_PROJECT_ID`, `POSTHOG_ORGANIZATION_ID`.
- Sandbox infra already exists for the agent platform: `products/agent_platform/services/agent-sandbox-host` (one image consumed by both `DockerSandboxPool` and `ModalSandboxPool`; per-invoke `dispatch.js` protocol over `request.json`/`response.json`).
- npm publish precedent: `publish-quill-npm.yml` (workflow_dispatch, `Release` environment, serialized concurrency). `@posthog/sdk` and `@posthog/api` are both unclaimed on npm.

---

## 2. `@posthog/sdk` — TypeScript SDK plan

### 2.1 Goals

- `import { client } from '@posthog/sdk'` → default client configured from env (`POSTHOG_API_KEY`, `POSTHOG_HOST`, `POSTHOG_PROJECT_ID`).
- `createClient({ apiKey, host, projectId, fetch })` for explicit initialization.
- Unified, discoverable surface: `client.featureFlags.list()`, `client.featureFlags.create({...})`, `client.query.execute({...})`.
- Input/output types generated from the OpenAPI spec — never handwritten.
- Isomorphic runtime (browser, node, workers, sandboxes): fetch-based, zero node-only deps, injectable `fetch` for proxied/sandboxed transports.
- Same curated surface, descriptions, and semantics as the MCP tools (soft deletes, response filtering), so agent-written scripts and MCP tools behave identically.

### 2.2 Package location and name

- **Location:** `packages/sdk` (cross-product code belongs in top-level `packages/`, per repo conventions; `packages/` currently holds only `quill`). Add to `pnpm-workspace.yaml`.
- **Name:** `@posthog/sdk` (unclaimed on npm; publishing under the `@posthog` org needs org-owner approval — same path quill took).
- Dual ESM/CJS build via tsup (or esbuild, matching `services/mcp` tooling), `exports` map, `types` included. No runtime dependencies ideally (see Zod decision below).

### 2.3 Architecture: handwritten core + generated resources

```text
packages/sdk/
├── package.json                  # @posthog/sdk
├── scripts/generate.ts           # SDK emitter (new codegen step)
├── src/
│   ├── core/
│   │   ├── http.ts               # HttpClient: fetch wrapper, auth header, retries, typed errors
│   │   ├── errors.ts             # PostHogApiError / PermissionError / ValidationError
│   │   ├── config.ts             # env resolution + createClient options
│   │   └── scope.ts              # lazy org/project resolution (GET /api/users/@me/) when not configured
│   ├── generated/                # committed, regenerated by hogli build:openapi
│   │   ├── types.ts              # request/response types (Orval schemas pass)
│   │   ├── resources/<domain>.ts # FeatureFlagsResource, InsightsResource, …
│   │   └── client.ts             # PostHogClient composing all resources
│   └── index.ts                  # createClient(), lazy default `client`
```

**Handwritten core.** Extract the transport out of `services/mcp/src/api/client.ts` rather than rewriting it: the generic `request<T>()`, header construction, 429 retry, and error mapping move into `packages/sdk/src/core/http.ts`. `services/mcp`'s `ApiClient` then wraps the SDK core (it keeps MCP-only concerns: session/conversation header forwarding, `X-PostHog-Client: mcp`, SSE streaming). This makes the MCP server the SDK's first production consumer and prevents the two transports from drifting.

**Generated resource layer.** A new emitter (`packages/sdk/scripts/generate.ts`) walks the same YAML definitions + OpenAPI spec that `generate-tools.ts` uses, and emits one method per operation:

```ts
export class FeatureFlagsResource {
  constructor(
    private http: HttpClient,
    private scope: ScopeResolver
  ) {}

  /** List feature flags for the project. */
  async list(params?: FeatureFlagsListParams, opts?: RequestOptions): Promise<Paginated<FeatureFlag>> {
    const projectId = await this.scope.projectId(opts)
    return this.http.request({
      method: 'GET',
      path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/`,
      query: params,
    })
  }
}
```

The heavy lifting — operation resolution, `project_id`/`organization_id` auto-injection, param include/exclude/rename, path construction, `soft_delete` → PATCH translation — already exists in `generate-tools.ts`. Extract those pure parts into a shared library (natural home: `tools/openapi-codegen`, which both generators already depend on) so the MCP-handler emitter and the SDK emitter are two thin frontends over one operation model.

**Types, not Zod, in the public surface.** SDK method signatures use plain TypeScript types generated by the existing Orval `api.schemas.ts`-style pass (`client: 'fetch'`, types only). No runtime validation inside the SDK — the API validates anyway, and keeping Zod out keeps the sandbox/browser bundle small. The `.d.ts` output doubles as the agent-facing type reference in code-execution mode (§3.5). Zod schemas remain an MCP-server concern for tool-input validation.

**Discovery index as a codegen artifact.** Besides the resources, the emitter produces a machine-readable discovery index over the generated surface: for every resource method and every named type, a record of `{ symbol, one-line signature, JSDoc text, declaration source, referenced symbols }`, with per-symbol dependency closures and token sizes precomputed. This is the backing store for type-based schema discovery (§3.5) — agents search and read the API surface as TypeScript declarations with comments, which is far more condensed than JSON Schema. Serializer `help_text` already flows into these declarations as JSDoc via Orval, so descriptions stay single-sourced.

### 2.4 Surface selection: curated first, expandable

Source of truth for what's in the SDK = the same `products/*/mcp/*.yaml` definitions:

- **Phase 1:** every `enabled: true` tool becomes an SDK method. These operations are guaranteed to have curated descriptions, scopes, and sane semantics — and it makes the SDK surface identical to the MCP tool surface, which is exactly what code-execution mode needs.
- **Expansion knob:** add an optional per-tool `sdk: true | false` field to the YAML schema (default: follow `enabled`). This lets products expose an operation in the SDK without exposing it as an MCP tool (or vice versa), without inventing a second config layer.
- Namespacing: derive `client.<domain>.<action>()` from the `domain-action` tool-name convention (`feature-flags-list` → `featureFlags.list`). Legacy names that don't follow the convention (`create-feature-flag`) get an explicit mapping table in the emitter; a lint (extending `lint-tool-names.ts`) flags new deviations.

Full-API coverage (every OpenAPI operation, MCP-curated or not) is deliberately out of scope for v1 — the frontend's Orval fetch client already serves in-repo needs, and an uncurated public surface would freeze bad endpoint shapes into a published package.

### 2.5 Client initialization and the default client

```ts
import { client, createClient } from '@posthog/sdk'

// Explicit
const ph = createClient({
  apiKey: 'phx_…',
  host: 'https://eu.posthog.com', // default: https://us.posthog.com
  projectId: 123, // optional; lazily resolved from /api/users/@me/ if omitted
  fetch: customFetch, // optional transport override (proxies, tests, sandboxes)
})

// Default client — reads POSTHOG_API_KEY / POSTHOG_HOST / POSTHOG_PROJECT_ID lazily
await client.featureFlags.list()
```

- The default `client` is a lazy proxy: env is read on first call, not at import time, so importing the package in a browser (no `process`) never throws; calling without a key throws a clear `MissingApiKeyError` naming the env vars.
- Env var names match the existing CLI resolution order (`services/mcp/src/cli/config.ts`): `POSTHOG_API_KEY`, `POSTHOG_HOST`, `POSTHOG_PROJECT_ID`, `POSTHOG_ORGANIZATION_ID`. One convention across CLI, SDK, and sandbox.
- Accepted credentials: personal API keys (`phx_`), project secret API keys (`phs_`) where endpoints support them, and short-lived proxy tokens in sandbox mode (§3.4) — the SDK is agnostic; it just sends `Authorization: Bearer`.
- Per-call overrides: `opts?: RequestOptions` on every method (`projectId`, `signal`, extra headers).

### 2.6 Pipeline integration

Add one step to the `build:openapi` chain in `hogli.yaml`, after `build:openapi-mcp`:

```yaml
build:openapi-sdk:
  command: pnpm --filter=@posthog/sdk run generate
```

- Generated output is **committed** (matching `frontend/src/generated/**` and `services/mcp/src/tools/generated/**`), so consumers and CI never need a Django boot to build.
- CI: extend the existing MCP drift check (`ci-mcp.yml` runs `scaffold-yaml --sync-all` + regen) to also regenerate the SDK and fail on diff; add `typecheck` and unit tests for `packages/sdk`.
- Tests: msw-based unit tests for the core (auth header, retry, error mapping, env resolution) — same tooling `services/mcp` already uses. One parameterized generated-surface test asserting each resource method builds the expected method/path from the definitions snapshot.

### 2.7 Publishing and versioning

- Workflow modeled on `publish-quill-npm.yml`: `workflow_dispatch`, `Release` environment, serialized concurrency, OIDC npm auth. (Per repo policy, npm publishing stays on the public repo; no production image/deploy gating applies.)
- Start at `0.x` with an explicit "surface may change" notice; move to changesets-driven releases once the CLI and generated artifacts depend on it.
- The npm package must vendor its generated code — no workspace-only imports.

### 2.8 Adoption path (MCP, CLI)

1. **MCP server** consumes `@posthog/sdk` core as its transport (workspace dep) — §2.3.
2. **Generated MCP handlers** optionally become thin wrappers over SDK methods (`handler: (ctx, params) => ctx.sdk.featureFlags.create(params)`), collapsing the two emitters' output. This is a refactor, not a requirement — the shared operation-model extraction already prevents drift.
3. **CLI**: `posthog-cli api` gains a `run <script.ts>` subcommand that executes a script with the SDK preconfigured from the CLI's resolved config — the local, trusted-environment twin of the sandboxed MCP execution below.

### 2.9 Phases

| Phase | Deliverable                                                                                                                                        |
| ----- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0     | Extract shared operation model from `generate-tools.ts` into `tools/openapi-codegen`; extract transport core from `services/mcp/src/api/client.ts` |
| 1     | `packages/sdk` with core + generated resources for all enabled tools; `build:openapi-sdk` hogli step; CI drift check + tests                       |
| 2     | npm publish workflow; MCP server on SDK core; CLI `run` subcommand                                                                                 |
| 3     | `sdk:`-flag surface expansion per product team demand; changeset-based releases                                                                    |

### 2.10 Open questions

- **Pagination ergonomics:** return raw `{ results, next, previous }` (matches API) or add async-iterator helpers (`for await (const flag of client.featureFlags.iter())`)? Recommendation: raw in v1, iterators as a non-generated core helper later.
- **Response filtering:** MCP tools filter response fields (`response.include/exclude`) to save tokens. The SDK should return **unfiltered** API responses (apps want full objects); filtering stays in the MCP handler layer. Needs confirming when handlers are rebuilt on the SDK.
- **`@posthog/sdk` vs `@posthog/api` naming**, and relationship to `posthog-js`/`posthog-node` (analytics capture SDKs) — docs must draw the line clearly: this package is the _management API_ SDK, not event capture.

---

## 3. High-level design: MCP server with code execution

### 3.1 Motivation

Today an agent workflow like "find all flags rolled out under 10%, bump each to 25%, annotate the change" costs N tool calls, N model round-trips, and the full payload of every intermediate response in model context. In code-execution mode ("Cloudflare code mode") the agent writes one script:

```ts
import { client } from '@posthog/sdk'

const flags = await client.featureFlags.list({ active: true })
const low = flags.results.filter((f) => rolloutPct(f) < 10)
for (const f of low) {
  await client.featureFlags.update(f.id, { filters: bump(f.filters, 25) })
}
export default { updated: low.map((f) => f.key) }
```

One tool call, one round trip, only the final summary re-enters context. The existing `exec` dispatcher (progressive disclosure: `tools`/`search`/`info`/`schema`/`call`) is the stepping stone; code execution is the next rung, and the SDK is its prerequisite — the sandbox API surface _is_ `@posthog/sdk`.

### 3.2 Tool surface

Extend the single-`exec` paradigm rather than adding many tools:

- `exec run <typescript source>` — execute a script in a sandbox; returns the script's `export default` value (serialized + token-capped) plus captured `console` output.
- `exec types <query>` — search the SDK surface by TS types and JSDoc comments: matches type names, method signatures, and description text; returns one-line signatures (`featureFlags.update(id: number, body: PatchedFeatureFlag): Promise<FeatureFlag> — Update a feature flag.`) so the agent can pick what to expand.
- `exec types show <symbol | domain.method>` — return the full declaration plus its referenced types (precomputed closure from the discovery index, token-capped with drill-down hints), e.g. the `FeatureFlag` interface with the `FilterGroups` types it references.
- Existing verbs stay: trivial one-shot operations don't need a sandbox round trip.

### 3.3 Execution substrate

Three options, in recommended order:

1. **Reuse `agent-sandbox-host` pools (Docker on k8s / Modal)** — recommended start. Already productionized for the agent platform: canonical image, per-invoke `dispatch.js` protocol, pool warm-keeping, no network by default. Add a "run user script" dispatch mode: write the script + a pinned `@posthog/sdk` bundle into the workdir, execute with hard CPU/memory/wall-clock limits, collect `response.json`. Cost: tens-to-hundreds of ms dispatch latency on a warm pool — acceptable for scripts that replace multi-call workflows.
2. **V8 isolates in/beside the Hono runtime** (workerd sidecar, `isolated-vm`, or QuickJS-WASM) — lowest latency, but weaker isolation than a container and a larger security burden we own directly. Candidate optimization once usage patterns are known; the `exec run` contract doesn't change.
3. **Cloudflare dynamic Worker Loaders** — the literal Cloudflare pattern, but PostHog's MCP protocol is served by Hono on k8s (the CF Worker is only an OAuth edge router), so this would split execution across infrastructures and regions. Not preferred.

The substrate hides behind a `SandboxExecutor` interface (mirroring `selectSandboxPool()` in `@posthog/agent-shared`) so it can be swapped without touching the tool.

### 3.4 Credential isolation — the load-bearing design decision

The user's real API key must **never** enter the sandbox; agent-authored code is untrusted by definition (prompt injection can author exfiltration code).

```text
agent ──(exec run script)──▶ MCP Hono runtime
                              │ 1. mint ephemeral token T (TTL ≈ script timeout, single execution id,
                              │    scopes = intersection of user's key scopes and tool policy)
                              │    — same HMAC-signed-state machinery as confirmed_action
                              │    (MCP_SIGNED_STATE_KEY)
                              ▼
                            sandbox (no general egress)
                              env: POSTHOG_API_KEY=T
                                   POSTHOG_HOST=https://<mcp>/sandbox-api/<execution-id>
                              script: import { client } from '@posthog/sdk'  ← works unchanged
                              ▼  (only reachable endpoint)
                            MCP API proxy endpoint
                              │ verifies T, enforces scopes + per-execution rate/size caps,
                              │ blocks destructive endpoints without confirmation (§3.6),
                              │ emits $mcp_tool_call-style analytics per underlying API call
                              ▼
                            PostHog Django API (real user token attached server-side)
```

This is exactly why the SDK's env-default initialization matters: the sandbox harness sets two env vars and every script gets a fully working, fully constrained client with zero boilerplate. The proxy — not the sandbox — is the security boundary; the sandbox's egress allowlist (proxy host only) is the second layer.

### 3.5 Schema discovery through TS types, not JSON Schema

The agent-facing discovery interface should be TypeScript declarations + JSDoc, not JSON Schema. Rationale:

- **Density.** A TS interface with comments carries the same information as its JSON Schema in a fraction of the tokens — no `"type": "object"` scaffolding, unions are `'a' | 'b'`, optionality is `?`, nesting is flat declaration references instead of inline expansion. The existing `exec info`/`schema` verbs already fight JSON Schema verbosity with `summarizeSchema` + drill-down hints; TS declarations are the systemic fix, not another mitigation.
- **Familiarity.** Models read and write TS constantly; they parse `Partial<FeatureFlag>` and discriminated unions natively, and the declaration the agent reads is literally the type it will program against in `exec run` — discovery output and coding surface are the same artifact, so there's no schema→code translation step to get wrong.
- **Single source of truth.** Serializer `help_text` → OpenAPI descriptions → Orval JSDoc. Improving a serializer description improves API docs, MCP tool schemas, and type-search results in one edit.

Mechanics (backed by the discovery index from §2.3):

- Search runs over symbol names, method signatures, and JSDoc text; results are one-line signatures grouped by domain. Expansion (`types show`) serves the precomputed declaration slice with its type closure, token-capped, with `hint` markers on truncated members — mirroring the existing `summarizeSchema` UX so agents don't need new habits.
- The index is built at codegen time (a TS-morph/compiler-API pass over the generated `.d.ts`), shipped as a static artifact with the MCP image and the CLI — search is a lookup, never runtime type-walking.
- Full per-domain `.d.ts` slices also ship as MCP resources for clients that prefer loading whole files into context; the v2 skills bundle gets a `writing-posthog-scripts` skill with patterns (pagination loops, error handling, `export default` contract).
- JSON Schema doesn't disappear: the MCP protocol requires it for tool registration (v1 clients, `exec info`/`schema` verbs keep working). It stops being the thing agents _read_ and remains the thing protocols _validate against_.

Context economy for results: the harness serializes the script's return value, token-caps it, and (later) can spill full results to an MCP resource/artifact the agent can page through — same pattern as the existing formatted-results override.

### 3.6 Destructive operations

The `confirmed_action` prepare/execute paradigm must survive code mode. Enforcement lives in the API proxy (not in the model-visible SDK): endpoints flagged destructive in the YAML definitions are rejected by the proxy unless the execution was created with a confirmation token obtained via the existing `-prepare` flow (or the client passed `--confirm` semantics per the CLI convention). Scripts therefore fail fast with a message telling the agent to run the prepare step and re-submit — the signed-state machinery is reused as-is.

### 3.7 Risks and open questions

- **Security review is a hard gate**: untrusted code execution, egress lockdown verification, resource-abuse limits (CPU/mem/time quotas, concurrency caps per user), tenant isolation between concurrent executions.
- **Cost/quota model**: sandbox seconds per org; needs metering before GA.
- **Latency budget**: warm-pool sizing for interactive agent loops; measure before choosing substrate option 2.
- **SDK version pinning in the sandbox**: the sandbox image vendors a specific `@posthog/sdk` build; it must be regenerated/redeployed on the same cadence as the MCP image (both come from `hogli build:openapi` outputs, so the existing `cd-mcp-image.yml` flow extends naturally).
- **Relationship to SQL-first v2**: complementary, not competing — `execute-sql` remains the read path; code execution is the orchestration/mutation path. Instructions should steer agents accordingly.

### 3.8 Phasing

| Phase | Deliverable                                                                                                                                                                                                             |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A     | SDK ships (§2); type-search discovery (`exec types` / `types show`, discovery index) + script-writing skill; `posthog-cli api run` for local/trusted execution (no sandbox needed — user's own machine, user's own key) |
| B     | API proxy endpoint + ephemeral token minting on the Hono runtime (usable by phase A CLI too, as an opt-in hardened mode)                                                                                                |
| C     | `exec run` on the Docker/Modal sandbox pool behind a feature flag, PostHog Code + Claude Code as first consumers                                                                                                        |
| D     | Result spilling to resources, latency work (isolate substrate evaluation), GA + docs                                                                                                                                    |

Phase A alone already delivers most of the agent value in coding-agent contexts (Claude Code, PostHog Code run scripts locally via the CLI); B/C extend it to hosted, untrusted contexts (claude.ai, Slack agents, cloud runs).
