# Plan: `@posthog/sdk` (TypeScript) on the MCP codegen pipeline + code-execution MCP

Status: proposal; first implementation landed behind the `mcp-code-execution` feature flag.
Owner: Max AI / MCP.

Implemented so far (all dark behind the flag):
`packages/sdk` (§2, generated surface + typed query wrappers);
the codegen artifacts (§2.3/§3.5/§3.6.2 — discovery index, mutation classifier table, rolled-up SDK `.d.ts`, emitted by the SDK generator into `services/mcp/src/generated/code-exec/`);
the plan/apply engine (§3.6 — recorder/enforcer transports, sentinel binding, signed plan tokens, plan store) in `services/mcp/src/lib/code-exec/`;
and the exec verbs `types`, `types show`, `run`, `apply` (§3.2) with the compile gate and a dev/test-only local VM executor in `services/mcp/src/tools/code-exec/`.
Not yet implemented: the production sandbox substrate (Modal pool, §3.3), the standalone API proxy endpoint + ephemeral tokens (§3.4 — the current transports run in-process), field-diff plan rendering and the plan-review UI app (§3.6.6), and npm publishing (§2.7).

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

- `exec run <typescript source>` — execute a script in a sandbox.
  The source is **compile-checked before dispatch** (see below); scripts that don't typecheck never reach the sandbox.
  Read-only scripts return the script's `export default` value (serialized + token-capped) plus captured `console` output directly.
  Scripts that attempt mutations return a **plan** — the recorded mutation set rendered as a diff, plus the script's _provisional output_ (§3.6.1) — and a signed confirmation token instead of applied results; see §3.6.
- `exec apply <confirmation token>` — execute a previously planned script for real, with the confirmed plan enforced as a contract (§3.6).
- `exec types <query>` — search the SDK surface: matches type names, method signatures, JSDoc, and the **full tool metadata** (curated descriptions, titles, categories from the YAML definitions — richer than what fits in code comments).
  Returns one-line signatures (`featureFlags.update(id: number, body: PatchedFeatureFlag): Promise<FeatureFlag> — Update a feature flag. [requires feature_flag:write ✓]`) so the agent can pick what to expand.
- `exec types show <symbol | domain.method | domain>` — return the requested declaration **plus its related types, greedily filled to the token budget** (BFS over the reference graph from the precomputed closure: direct references first, then transitive), so one call usually answers instead of a drill-down sequence.
  Only members that exceed the budget are truncated, each carrying a `hint` naming the follow-up path.
  A bare `domain` argument dumps the whole resource class signature the same way.
- Existing verbs stay: trivial one-shot operations don't need a sandbox round trip.
- Contingent (if client transport behavior forces an async model, §3.7): `exec status <execution id>` / `exec cancel <execution id>` for long-running scripts, and `exec result <resource id>` for paging spilled results.

**Compile gate.**
`exec run` and `exec apply` typecheck the source against the pinned SDK `.d.ts` plus contract lints (must `export default`, no `require` of unavailable modules) before any sandbox is dispatched.
Latency is validated: `tsgo` (already used by `services/mcp`) checks an agent script against the full ~4 MB `.d.ts` in **~180 ms cold**, and a warm `ts.createLanguageService` daemon does ~25 ms per check.
Diagnostics return to the agent as structured, file/line-anchored errors — the same types it read during discovery, so the fix loop is immediate and costs no sandbox time.

The gate is only as strong as the response schemas behind it.
Today, response-side objects are weakly typed where serializers don't structure output (e.g. `FeatureFlag.filters` is `{ [key: string]: unknown }` while the _input_ filters type is fully structured) — enough that §3.1's own flagship script fails `tsc` against the current types, and agents blocked this way will learn to cast to `any`, eroding the gate.
**Prerequisite workstream (Django, not SDK):** enrich serializer _response_ schemas for the objects agent scripts read most (feature flag `filters`, surveys, experiments), the same `help_text`/`@extend_schema_field` discipline already applied to inputs.
Two SDK-side companions: export the generated `*Params` input types from the package root (currently unimportable, so agents can't type helper functions), and structurally type `query.run`'s body beyond `{ kind: string }` where feasible.

**Scope awareness.**
The session knows the token's resolved scopes (already resolved for tool gating today), and the classifier table (§3.6.2) knows each method's required scopes — so discovery is scope-annotated per session: every signature in `exec types` results carries `[requires <scope> ✓]` or `[requires <scope> — missing on this token]`, and search returns gated matches separately with the missing scopes named, mirroring the existing `exec search` `scope_gated_matches` behavior.
Agents therefore know before writing a script which methods will be denied, instead of discovering it at run time; the plan pass double-checks (permission errors surface in the plan, before anything is confirmed).

### 3.3 Execution substrate

Three options, in recommended order:

1. **Reuse the `agent-sandbox-host` pools** — recommended start; already productionized for the agent platform (canonical image, per-invoke `dispatch.js` protocol). **Modal is the production substrate** (isolated microVMs outside PostHog's infrastructure); the Docker pool is local-dev only (`selectSandboxPool` enforces this split). Known work, validated by a dry-run spike against the real code:
   - The dispatch protocol is hardwired to a CJS `tools/<id>/compiled.js` layout with no env-var injection on `exec` — running agent scripts needs a new dispatch mode (ESM + top-level await + `export default`), env plumbing (the credential story in §3.4 rides on two env vars), and an SDK bundle laid into the workdir. Changes couple to the image release cadence (GHCR publish → chart `SANDBOX_HOST_IMAGE` rollout).
   - **There is no warm pool today** — sandboxes are acquired per session, and a fresh Modal sandbox boots in ~5–15 s on a warm image. Per-invoke dispatch after acquisition is cheap. Budget a pre-warmed pool as new work, or accept multi-second first-run latency per session at launch.
   - CPU quotas are not currently wired in either pool (memory/pids only on Docker) — the §3.7 resource-limit line is a build item, not a checkbox.
2. **V8 isolates in/beside the Hono runtime** (workerd sidecar, `isolated-vm`, or QuickJS-WASM) — lowest latency, but weaker isolation than a microVM and a larger security burden we own directly. Candidate optimization once usage patterns are known; the `exec run` contract doesn't change.
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
                              │ runs in plan or enforce mode per execution (§3.6),
                              │ emits $mcp_tool_call-style analytics per underlying API call
                              ▼
                            PostHog Django API (real user token attached server-side)
```

This is exactly why the SDK's env-default initialization matters: the sandbox harness sets two env vars and every script gets a fully working, fully constrained client with zero boilerplate. The proxy — not the sandbox — is the security boundary; sandbox egress restriction is the second layer.

**Egress restriction, concretely (per substrate).**
The token is not the asset — it's the user's own credential, scope-intersected and TTL-bound.
Egress lockdown exists to close the _exfiltration channel_ in the injection scenario: attacker-writable PostHog data (event properties, survey responses) steers the agent into a script that queries sensitive data and ships it somewhere the attacker can read.

- **Modal (production):** sandboxes are isolated microVMs outside PostHog's infrastructure, so there is no internal network to move laterally into.
  The only egress knob is `outboundCidrAllowlist` (CIDR, not hostname), and the script chooses Host/SNI — so the allowlist is only sound if the IPs behind `mcp.{us,eu}.posthog.com` serve _nothing else_.
  If those IPs are shared ingress that also serves other PostHog hostnames — the public capture endpoint especially — a sandboxed script can exfiltrate through PostHog itself by sending stolen data as events to an attacker-owned project's token.
  **Prerequisite for Phase C:** verify the ingress topology; if shared, provision a dedicated ingress IP/hostname for the sandbox API so the CIDR allowlist is exact.
- **Docker (local dev only):** hard-codes `--network=none`; local plan/apply testing needs a UDS-mounted forwarder or host networking. Dev ergonomics, not a security surface.

Note the CF Worker edge only routes `/mcp*`; the sandbox proxy URL targets the direct Hono hostnames (`mcp.us.posthog.com` / `mcp.eu.posthog.com`), where a `/sandbox-api/:executionId/*` route slots into the existing app with its own auth.

### 3.5 Schema discovery through TS types, not JSON Schema

The agent-facing discovery interface should be TypeScript declarations + JSDoc, not JSON Schema. Rationale:

- **Density.** A TS interface with comments carries the same information as its JSON Schema in a fraction of the tokens — no `"type": "object"` scaffolding, unions are `'a' | 'b'`, optionality is `?`, nesting is flat declaration references instead of inline expansion. The existing `exec info`/`schema` verbs already fight JSON Schema verbosity with `summarizeSchema` + drill-down hints; TS declarations are the systemic fix, not another mitigation.
- **Familiarity.** Models read and write TS constantly; they parse `Partial<FeatureFlag>` and discriminated unions natively, and the declaration the agent reads is literally the type it will program against in `exec run` — discovery output and coding surface are the same artifact, so there's no schema→code translation step to get wrong.
- **Single source of truth.** Serializer `help_text` → OpenAPI descriptions → Orval JSDoc. Improving a serializer description improves API docs, MCP tool schemas, and type-search results in one edit.

Mechanics (backed by the discovery index from §2.3):

- The index record per method carries more than the code shows: symbol, one-line signature, the SDK JSDoc, **and the full tool metadata** (curated description, title, category, required scopes) from the YAML definitions — descriptions are searchable in full even where the emitted JSDoc truncates them. Search runs over all of it; results are one-line signatures grouped by domain, scope-annotated for the session's token (§3.2). Expansion (`types show`) serves the precomputed declaration slice with its reference closure greedily filled to the token budget, with `hint` markers only on members that didn't fit — mirroring the existing `summarizeSchema` UX so agents don't need new habits.
- The index is built at codegen time (a TS-morph/compiler-API pass over the generated `.d.ts`), shipped as a static artifact with the MCP image and the CLI — search is a lookup, never runtime type-walking.
- Full per-domain `.d.ts` slices also ship as MCP resources for clients that prefer loading whole files into context; the v2 skills bundle gets a `writing-posthog-scripts` skill with patterns (pagination loops, error handling, `export default` contract).
- JSON Schema doesn't disappear: the MCP protocol requires it for tool registration (v1 clients, `exec info`/`schema` verbs keep working). It stops being the thing agents _read_ and remains the thing protocols _validate against_.

Context economy for results: the harness serializes the script's return value, token-caps it, and (later) can spill full results to an MCP resource/artifact the agent can page through — same pattern as the existing formatted-results override.

### 3.6 Plan/apply execution: dry-run previews for mutating scripts

The `confirmed_action` prepare/execute paradigm assumes the arguments of a destructive action are known before execution.
Code mode breaks that assumption: a script _discovers_ its targets at runtime ("find all flags under 10% and update the stale ones"), so there is nothing meaningful to sign upfront.
Plan/apply replaces per-tool confirmation with per-execution confirmation: the user confirms the **actual set of mutations the script produced**, and that confirmed set is enforced as a contract on the run that executes them.
This is the Terraform plan/apply model, implemented as a mode on the API proxy from §3.4 — no sandbox or SDK changes.

#### 3.6.1 Two-pass model

**Pass 1 — plan.** Every script runs in plan mode first.
The proxy passes reads through to the real API untouched and intercepts mutations: each intercepted call is recorded as `{sequence, method, path, body, operation}` and answered with a synthetic response instead of being forwarded.

- **Zero mutations recorded** → the plan run _was_ the real run.
  Return the script's results directly; no confirmation, no second pass.
  Read-only scripts — the majority — pay nothing for this feature.
- **Mutations recorded** → store the script server-side and return the rendered plan, the script's **provisional output** (its `export default` value as computed during the plan pass, clearly labeled as provisional since it was produced against synthetic mutation responses and sentinel IDs), and a signed confirmation token.
  The provisional output is what lets both the agent and the user judge that the script's _logic_ is right — the plan shows what would change, the provisional output shows what the script concluded — before anything is applied.
  Permission errors from reads (and scope checks against planned mutations, §3.2) also surface here, so a script doomed by a missing scope is caught before confirmation, not during apply.

**Pass 2 — apply.** On `exec apply <token>`, the harness re-runs the _stored_ script live, with the proxy in enforce mode: every mutation the script attempts is matched against the confirmed plan (method, path, body, modulo placeholder bindings — §3.6.3).
A mutation not in the plan aborts the run immediately with a structured "plan divergence" error.

Re-running the script — rather than replaying the recorded mutation list — is the load-bearing choice:

- Real IDs from real creates flow into downstream calls naturally; no symbolic execution needed.
- If the world changed between plan and apply (another user edited a flag, a list query returns different rows), the script's mutations diverge from the plan and the enforcer aborts with "the world changed since you confirmed — re-plan."
  Staleness detection falls out for free.
- The confirmation is binding on _what actually executes_, not on the script text or the agent's stated intent.

The cost is one extra script execution for mutating scripts (reads run twice).
Scripts execute in seconds; the guarantee is worth the double read.

#### 3.6.2 Mutation classifier

The proxy sees raw HTTP, and "mutation" is not `method !== 'GET'`: `POST /api/environments/:id/query/` is a read.
A classification table is generated at codegen time from the same YAML definitions + OpenAPI spec the SDK is built from — the `readOnly` and `destructive` annotations already exist per operation — and ships as a static artifact with the proxy (same distribution as the discovery index, §3.5).

- Each entry: operation id, method, path template (covering both `/api/projects/` and `/api/environments/` aliases), `readOnly`, `destructive`, `soft_delete` marker + body pattern, object type, display-name field (for plan rendering, §3.6.6).
- Soft deletes are invisible at the proxy without the metadata: the SDK translates `delete()` to `PATCH {deleted: true}` client-side, byte-identical to an update on the wire.
  The classifier's `soft_delete` entry + body match is what lets §3.6.6 render them loud.
- Requests that match no classified operation (escape hatches like `query.run()` with an unknown kind, future endpoints) are treated as **mutations unless proven reads** — fail closed.
  Note the collision this creates: fail-closed turns the single most important read path (`POST /query/` with an arbitrary kind) into a phantom mutation, so **the query-endpoint classification must be settled before Phase B ships anything** — it is a prerequisite, not an open question to defer.
- `execute-sql` / HogQL with mutating statements: the proxy submits queries through the read path and relies on the query endpoint's own read-only enforcement.
  If that guarantee turns out not to hold for some node kind, those kinds get blocked in scripts until classified.

#### 3.6.3 Synthetic responses and sentinel binding for create-then-use chains

During planning, a create must return _something_ so the script can continue and reveal its downstream mutations.
Two facts from the dry-run spike shape this design:

- **There is no runtime source of response schemas today.** No committed OpenAPI spec, TS types are erased, and the MCP Zod modules cover requests only.
  The SDK emitter must therefore also emit a **per-operation response-schema artifact** (at minimum: identifier fields and their types; ideally full shapes) at codegen time, shipped with the proxy like the classifier table.
  Until it exists, the only synthesis heuristic is echoing the request body — which the spike showed produces `undefined` for any server-computed field a script reads, guaranteeing divergence.
- **Naive sentinels are type-lies visible to script logic.** A string sentinel in a `number`-typed field means `Number(created.id)` yields `NaN` and _silently_ steers the plan pass down one branch — undetected at plan time, and caught at apply only if the real value happens to land on the other branch.

Design, in two stages:

1. **Schema-aware primitive sentinels** (Phase B): identifier fields get sentinels of the schema-correct primitive type — reserved-range negative integers for numeric IDs, prefixed UUIDs/strings for string IDs — one per recorded mutation, globally unique within the execution.
   Non-identifier fields come from the response-schema artifact's defaults, with request-body echo for fields the request supplies.
   This kills the `NaN` class of silent corruption outright.
2. **Magic-mock access recording** (Phase C/D): plan mode injects a thin in-sandbox shim over the SDK transport (there is a JSON boundary between proxy and script, so live objects can't cross HTTP — but the harness owns the sandbox bundle, and `HttpClient.request` is patchable).
   Intercepted mutation responses become Proxy objects that (a) answer coercion via `Symbol.toPrimitive` with hint-appropriate sentinel values, and (b) **record every property the script reads**.
   Access recording converts silent unfaithfulness into a detected one: a plan whose script only passed IDs through is marked _faithful_; one that read synthetic fields (`created.key`, a computed rollout) is marked **low-confidence**, and the plan response says which fields — the user sees the flag before confirming.
   Honest limits: `typeof` checks and `===` against literals can't be trapped and still diverge — but the read was recorded, so those plans are already flagged rather than passing silently.

When a sentinel appears inside a later recorded mutation (path or body, including embedded in strings), the plan stores a **reference** to the originating mutation, not a literal value.
At apply time the enforcer binds each reference positionally: mutation #1 executes for real, its actual response value is captured, and downstream calls are matched with that binding substituted.
Because sentinels are globally unique, substitution is textual and sound — validated end-to-end by the spike prototype (binding held through URL paths and inside body strings; divergence detection fired in the negative tests).

Known limit: scripts that _branch on mutation results_ can produce different mutations at apply time than at plan time.
The enforcer catches this as plan divergence — the honest failure mode — and the agent re-plans; access recording (stage 2) additionally flags such plans as low-confidence before anything is confirmed.
The dominant agent script shape (read → compute → mutate, mutations as dataflow leaves) is unaffected.

#### 3.6.4 Confirmation token

The signed-state machinery from `confirmed_action` is reused as-is (`MCP_SIGNED_STATE_KEY`, HMAC-SHA256):

- Signed payload: `{plan hash, script hash, user identity, resolved scope set, TTL, single-use nonce}` — hashes only; the script and full plan live in Redis, keeping the token small.
- The signed-state default TTL is 300 s by deliberate doctrine ("tuning is a code change, not a deployment knob"); the codec accepts per-instance `ttlSeconds`, so plan tokens get their own purpose-bound codec with a plan-appropriate TTL rather than a config override.
- The plan hash is computed over the normalized mutation list (stable field ordering, sentinels canonicalized), so the token is bound to the exact confirmed plan.
- The script is stored server-side keyed by its hash (Redis, TTL'd — the same session infra the Hono runtime already uses), so the agent cannot submit different code at apply time.
- `exec apply` verifies the signature, burns the nonce, loads the stored script, and runs the enforce pass.
- Expired token → the harness auto-re-plans and returns the fresh plan **plus a delta against the stale plan**; it never silently re-confirms.

#### 3.6.5 Partial failure and resume

If the apply pass fails at mutation 17 of 30 (API error, timeout, divergence), the receipt lists exactly which mutations were forwarded and their responses — the proxy recorded every call.
Recovery is the same loop: **re-plan**.
The fresh plan run reads the now-partially-mutated world and produces a plan for only the remaining work; the user confirms the remainder.
No idempotency keys, no checkpoint protocol — the plan/apply cycle is itself the resume mechanism.

#### 3.6.6 Plan rendering and receipts

Plans render in two forms:

- **Text** (all clients): grouped by object type and operation, updates shown as field-level diffs.
  For updates, the proxy fetches the current object during planning and diffs against the request body: `flag checkout-v2: rollout 10% → 25%`.
  Creates render with sentinel names ("new annotation: …"); deletes render loud and first.
  The classifier's object-type + display-name metadata (§3.6.2) drives naming.
- **Plan-review UI app** (ext-apps clients): an interactive diff view with a confirm affordance, built on the existing MCP UI-apps infrastructure.

After apply, the receipt carries: per-mutation outcome, links to every changed object (`_posthogUrl`-style), and activity-log references.
Optionally the harness writes an annotation summarizing the change set.

#### 3.6.7 Policy knobs and CLI parity

- Default: every mutating script requires confirmation.
- Org-level relaxation: auto-apply plans containing only non-destructive creates (annotations, insights, notebooks); always confirm plans containing updates, deletes, or anything flagged `destructive`.
  The classifier's annotations drive the split.
- The CLI (`posthog-cli api run`, Phase A) implements the same plan/apply verbs locally so behavior is identical in trusted and sandboxed runtimes, with `--yes` for scripted/CI use.
  Skills teach one workflow, not two.

#### 3.6.8 Build order and open questions

Build order:

1. Classifier table emission + proxy record/enforce modes + sentinel binding.
   Pure server-side; golden-script tests: read-only passthrough, create-chain binding, divergence abort, nonce reuse, expired-token re-plan.
2. `exec run` returning plans, `exec apply`, text rendering, receipts.
3. Field-diff rendering, plan-review UI app, org policy knobs.

Open questions to settle before Phase B:

- Whether any HogQL/query node kinds can mutate state; if so, block them in scripts until classified.
- Plan TTL vs long-lived client conversations — current answer is auto-re-plan with delta (§3.6.4); validate the UX against real clients.
- Whether synthetic plan-mode responses need per-operation schema fidelity beyond identifier fields (scripts that read non-ID fields off create responses during planning get schema-default values; measure how often that breaks real scripts).

### 3.7 Risks and open questions

- **Security review is a hard gate**: untrusted code execution, egress lockdown verification (§3.4 — dedicated ingress IP question), resource-abuse limits (CPU quotas are not currently wired in the pools; mem/time/concurrency caps per user), tenant isolation between concurrent executions.
- **Cost/quota model**: sandbox seconds per org; needs metering before GA.
- **Latency budget**: no warm pool exists today (§3.3) — first run in a session pays Modal sandbox boot (~5–15 s); pre-warmed pool sizing is new work, and the numbers decide whether substrate option 2 is worth revisiting.
- **SDK version pinning in the sandbox**: the sandbox image vendors a specific `@posthog/sdk` build; it must be regenerated/redeployed on the same cadence as the MCP image (both come from `hogli build:openapi` outputs, so the existing `cd-mcp-image.yml` flow extends naturally).
- **Proxy rate caps vs SDK retry**: the SDK retries 429s with up to a 30 s wait budget — a proxy that answers cap breaches with 429 makes sandboxed scripts silently sleep away their wall-clock. The proxy must deny with a non-retryable status (or `Retry-After: 0` semantics) for per-execution cap breaches.
- **SSE parity gap**: MCP tools built on `requestSSE` (session-recording summarization) have no SDK/code-mode counterpart; those remain tool-call-only until the SDK grows a streaming story. Document per tool.
- **Relationship to SQL-first v2**: complementary, not competing — `execute-sql` remains the read path; code execution is the orchestration/mutation path. Instructions should steer agents accordingly.

### 3.8 Phasing

| Phase | Deliverable                                                                                                                                                                                                             |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A     | SDK ships (§2); type-search discovery (`exec types` / `types show`, discovery index) + script-writing skill; `posthog-cli api run` for local/trusted execution (no sandbox needed — user's own machine, user's own key) |
| B     | API proxy endpoint + ephemeral token minting on the Hono runtime (usable by phase A CLI too, as an opt-in hardened mode); mutation classifier + proxy plan/enforce modes with golden-script tests (§3.6.8 step 1)       |
| C     | `exec run` (plan-returning) + `exec apply` on the Docker/Modal sandbox pool behind a feature flag, text plan rendering + receipts, PostHog Code + Claude Code as first consumers                                        |
| D     | Field-diff rendering + plan-review UI app + org policy knobs, result spilling to resources, latency work (isolate substrate evaluation), GA + docs                                                                      |

Phase A alone already delivers most of the agent value in coding-agent contexts (Claude Code, PostHog Code run scripts locally via the CLI); B/C extend it to hosted, untrusted contexts (claude.ai, Slack agents, cloud runs).
