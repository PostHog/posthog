# Plan: `@posthog/sdk` (TypeScript) on the MCP codegen pipeline + code-execution MCP

Status: proposal; implementation landed behind the `mcp-code-execution` feature flag, with the code-first surface mechanics behind a separate `mcp-code-first` flag.
Owner: Max AI / MCP.

Implemented so far (all dark behind the flags):
`packages/sdk` (§2, generated surface + typed query wrappers);
the codegen artifacts (§2.3/§3.5/§3.6.2 — discovery index, mutation classifier table, rolled-up SDK `.d.ts`, emitted by the SDK generator into `services/mcp/src/generated/code-exec/`);
the plan/apply engine (§3.6 — recorder/enforcer transports, sentinel binding, three-word plan ids, plan store with single-use consumption) in `services/mcp/src/lib/code-exec/`;
the exec verbs `types` (single verb; the earlier `types show` sub-verb is retired, see §3.2), `run`, `apply` (§3.2) with sucrase script lowering, an injected compile gate, and a local VM executor (dev/test-only on the server, trusted-local in the CLI) in `services/mcp/src/tools/code-exec/`;
the no-sandbox fast path for call-shaped scripts (§4.2 — available wherever the flag is on, including executor-less production: sandbox-requiring scripts there get a targeted redirect, and plans are pinned to the session project they were confirmed against);
the `sql` verb, the optional `script` parameter, and the `mcp-code-first` compatibility mechanics (§4.3 — discovery verbs aliased to `types`, `call` kept with a generated-`run` deprecation footer; active only where full script execution exists, matching the instruction arms);
discovery/executor decoupling with the `fast-path`/`full` availability levels (§4.4) and the code-first instruction variant (§4.4/§4.6 Phase 3 — flag-off output byte-identical);
the Phase 0 exec analytics (§4.6 — verb, run status, plan mutation count, fast-path and deprecated-verb flags);
and the CLI local execution mode (§4.8 — `types`/`run`/`apply` subcommands, file-backed plan store, in-process execution on the user's machine).
Not yet implemented: the production sandbox substrate (Modal pool, §3.3), the standalone API proxy endpoint + ephemeral tokens (§3.4 — the current transports run in-process), field-diff plan rendering and the plan-review UI app (§3.6.6), npm publishing (§2.7), and the §4.5 execution-ergonomics layer (transport wrapper, result handles — §4.6 Phase 2).

§4 records the surface-redesign decision adopted once the exec verbs landed end to end: code execution becomes the primary agent-facing interface (one mental model — TypeScript against `@posthog/sdk`), with a no-sandbox fast path for call-shaped scripts and the legacy `tools`/`search`/`info`/`schema`/`call` verbs demoted to a hidden compatibility layer.
It supersedes the "additive" positioning in §3.2 ("existing verbs stay") and §3.7 ("`execute-sql` remains the read path").

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
  Scripts that attempt mutations return a **plan** — the recorded mutation set rendered as a diff, plus the script's _provisional output_ (§3.6.1) — and a single-use plan id instead of applied results; see §3.6.
- `exec apply <plan-id>` — execute a previously planned script for real, with the confirmed plan enforced as a contract (§3.6); the id is a three-word phrase (§3.6.4).
- `exec types <query | TypeName... | domain.method | domain>` — one verb for both discovery questions, disambiguated by exactness (revised: the original design had a `types show` sub-verb returning the declaration plus its reference closure greedily BFS-filled to a token budget; live use showed that floods the agent with types it didn't ask for, so expansion is now lean and the sub-verb is retired, with a leading `show` token still accepted for compatibility).
  The input is tokenized on whitespace/commas; **if every token resolves exactly** (method id → type name → domain prefix) the verb enters fetch mode, otherwise the whole input is one search pattern.
  **Fetch mode** returns exactly the requested declarations, nothing more: a type renders its declaration followed by a references hint (`References: A, B — run "types A B" for declarations`) instead of inlined bodies; a method renders its one-line signature + description + references hint; a bare domain lists the resource's method signatures.
  **Search mode** matches type names, method signatures, JSDoc, and the **full tool metadata** (curated descriptions, titles, categories from the YAML definitions — richer than what fits in code comments), returning one-line signatures (`featureFlags.update(id: number, body: PatchedFeatureFlag): Promise<FeatureFlag> — Update a feature flag. [requires feature_flag:write ✓]`) plus matching type names, so the agent picks exact symbols to fetch next.
  Responses are capped at a fixed character limit: whole declarations are included in request order while they fit, and anything cut is named in a truncation hint carrying the follow-up call (an oversized single declaration truncates at the cap and points at its referenced types) — the response never exceeds the cap, and every truncation names the next command, so agents never need to offload results elsewhere.
- ~~Existing verbs stay: trivial one-shot operations don't need a sandbox round trip.~~ Superseded by §4: trivial one-shot operations are served by the fast path (§4.2) — a call-shaped `run` script dispatches through the existing tool handler with `call`-equivalent latency and no sandbox — and the legacy verbs become a hidden compatibility layer (§4.3).
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

- The index record per method carries more than the code shows: symbol, one-line signature, the SDK JSDoc, **and the full tool metadata** (curated description, title, category, required scopes) from the YAML definitions — descriptions are searchable in full even where the emitted JSDoc truncates them. Search runs over all of it; results are one-line signatures grouped by domain, scope-annotated for the session's token (§3.2). Expansion (exact symbols passed to `types`) serves precisely the requested declaration slices, with referenced type names surfaced as fetch hints rather than inlined bodies, under a fixed response character cap (§3.2) — hints mirror the existing `summarizeSchema` UX so agents don't need new habits.
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
- **Mutations recorded** → store the script server-side and return the rendered plan, the script's **provisional output** (its `export default` value as computed during the plan pass, clearly labeled as provisional since it was produced against synthetic mutation responses and sentinel IDs), and a single-use plan id (§3.6.4).
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

#### 3.6.4 Confirmation reference: a three-word plan id

(Revised: the original design reused the `confirmed_action` HMAC signed-state machinery — a ~600-char `eyJ…` token carrying `{plan hash, script hash}` claims. Live use showed that costs the agent ~150–200 LLM tokens of verbatim copying per mutation flow for no security benefit, because the store, not the signature, was always the root of trust: the script and plan live server-side and `apply` cannot run without loading them. The signed token is replaced by a stored-capability reference.)

`run` returns a **three-word plan id** (`apply cat-assistant-tree` — words drawn from a vendored 1296-word passphrase list), and the plan record itself carries everything the old token proved:

- **Storage**: the script + plan + user identity are stored server-side (Redis on the hosted path, files in CLI local mode §4.8) under the key `<sub>:<phrase>`, TTL 600 s. The agent cannot submit different code at apply time because apply executes the _stored_ script — unchanged from the original design.
- **User binding**: the key embeds the caller's identity (`sub`), so a phrase is only resolvable by the identity that minted it — cross-user guessing is structurally impossible, and applying your own plan is not an escalation.
- **Unguessability**: 3 words from 1296 ≈ 31 bits (~2.2 B combinations) per user, against a 10-minute TTL, single-use consumption, and an authenticated, rate-limited endpoint. No HMAC needed; `MCP_SIGNED_STATE_KEY` is no longer a code-exec dependency (the `confirmed_action` machinery elsewhere is untouched).
- **Single-use**: `apply` atomically consumes the record before executing (matching the old burn-nonce-before-execute semantics), leaving a consumed tombstone for the remaining TTL so a second apply gets a distinct "already been applied — a plan id is single-use" message; unknown, expired, and mistyped ids collapse into one not-found message.
- The plan hash is still computed over the normalized mutation list (stable field ordering, sentinels canonicalized) and stored on the plan record — it drives enforce-mode matching, no longer token claims.
- Expired id → the harness auto-re-plans and returns the fresh plan **plus a delta against the stale plan**; it never silently re-confirms.
- Ergonomics: apply input is normalized (case, whitespace/underscores → dashes), so `apply Cat Assistant Tree` resolves; three short words survive chat-relay and human retyping in a way a 600-char blob does not.

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
- The CLI (`posthog-cli api run`, Phase A) implements the same plan/apply verbs locally so behavior is identical in trusted and sandboxed runtimes, with `--yes` for scripted/CI use. Concrete design in §4.8.
  Skills teach one workflow, not two.

#### 3.6.8 Build order and open questions

Build order:

1. Classifier table emission + proxy record/enforce modes + sentinel binding.
   Pure server-side; golden-script tests: read-only passthrough, create-chain binding, divergence abort, plan-id reuse, expired-id re-plan.
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
- **Relationship to SQL-first v2**: complementary, not competing. Under §4, SQL keeps first-class standing inside the code-first grammar — a dedicated `sql <hogql>` verb (fast-pathing to the `execute-sql` handler) plus `client.query.sql()` for use inside scripts (§4.3) — rather than remaining a separately-taught modality.

### 3.8 Phasing

| Phase | Deliverable                                                                                                                                                                                                              |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A     | SDK ships (§2); type-search discovery (`exec types`, discovery index) + script-writing skill; `posthog-cli api run` for local/trusted execution (no sandbox needed — user's own machine, user's own key; design in §4.8) |
| B     | API proxy endpoint + ephemeral token minting on the Hono runtime (usable by phase A CLI too, as an opt-in hardened mode); mutation classifier + proxy plan/enforce modes with golden-script tests (§3.6.8 step 1)        |
| C     | `exec run` (plan-returning) + `exec apply` on the Docker/Modal sandbox pool behind a feature flag, text plan rendering + receipts, PostHog Code + Claude Code as first consumers                                         |
| D     | Field-diff rendering + plan-review UI app + org policy knobs, result spilling to resources, latency work (isolate substrate evaluation), GA + docs                                                                       |

Phase A alone already delivers most of the agent value in coding-agent contexts (Claude Code, PostHog Code run scripts locally via the CLI); B/C extend it to hosted, untrusted contexts (claude.ai, Slack agents, cloud runs).

§4.6 refines this phasing for the surface redesign: an analytics-first Phase 0, the fast path shipping to production before the sandbox exists, and A/B-gated instruction flips.

---

## 4. Surface redesign: code-first exec

Status: adopted direction, decided after the §3.2 verbs landed end to end behind the flag.

With `mcp-code-execution` on, the server ships two parallel stacks describing the same 617 operations: JSON-schema discovery (`info`/`schema` plus mandatory drill-down prose) with per-tool `call`, and TS discovery (`types`) with scripted `run`/`apply`.
Two discovery languages, two execution paths, and two confirmation systems (`call --confirm` vs `apply <token>`) spend instruction budget and agent attention without buying capability — every tool has an SDK method and vice versa, generated from the same artifacts.
This section is the plan of record for collapsing that to one surface.

### 4.1 Thesis: one mental model, two execution strategies

The agent always writes TypeScript against `@posthog/sdk`; the **server** picks the execution strategy.
The load-bearing observation: **the sandbox and the security boundary are different components.**
All API traffic flows through the server-side transport (§3.4 proxy; today the in-process recorder/enforcer transports), which does all mutation gating, scope enforcement, and credential isolation.
The sandbox exists for exactly one purpose — running arbitrary untrusted JavaScript.
A script that requires no JavaScript execution requires no sandbox, and single API calls with literal arguments (the dominant shape of agent traffic today) are statically recognizable as exactly that.

- **Fast path** (§4.2): call-shaped scripts dispatch through the existing generated tool handlers — one HTTP request, no sandbox, zero user code executed. Same latency, TOON-optimized output, UI-app attachment, and inner-tool analytics attribution as `call` today.
- **Sandbox path**: everything else (loops, filters, variables, multi-call dataflow) takes compile gate → plan/apply exactly as specified in §3.6.

The agent never chooses between modalities, so the "use call for simple things" fork disappears from the instructions.
The fast path is what makes the code-first position credible: without it, every "list 3 flags" pays a sandbox boot; with it, code-first ships to production **before** the Modal pool exists, because the fast path never executes user code (the `LocalVmExecutor` dev-only restriction does not apply).

### 4.2 The fast path

A script qualifies iff its AST (already produced by `rewriteModuleToCjs`'s TS-compiler parse) matches a single SDK call with literal arguments:

```ts
import { client } from '@posthog/sdk'
export default await client.<domain>.<method>(<args>)   // args: JSON-literal constructible only
```

Rules, deliberately strict:

- Exactly one SDK call expression, and it is the `export default` expression (or one `const x = await …; export default x` pair).
- Arguments are string/number/boolean/null literals, array/object literals thereof, or substitution-free template literals. Any identifier, computed value, ternary, or method chain → sandbox path.
- No other statements with effects (type-only imports and comments are fine).

Execution: resolve `domain.method` → `toolName` via the discovery index (it already carries `toolName` per method) → validate the extracted args against the tool's Zod schema (better error messages than `tsc`; the fast path skips the compile gate entirely) → dispatch the existing tool handler.
Latency: one AST parse (~5 ms) plus one HTTP request — identical to `call`.

Mutating fast-path calls do **not** bypass plan/apply — one uniform confirmation contract is worth more than saving a round trip.
Their plan is degenerate: the single extracted mutation, rendered instantly, with no synthetic responses and no provisional-output caveats; `apply` replays the call directly through the handler, again with no sandbox.
Single-mutation workflows therefore work end to end in production with zero sandbox dependency.

Do not widen the subset toward an interpreter: constant folding of literals is the ceiling; anything touching identifiers goes to the sandbox (a "small TS interpreter" is a second sandbox with none of the isolation).

### 4.3 Verb grammar

```text
types <query | TypeName... | domain.method | domain>
                                             # all tokens exact → the requested declarations (references as hints);
                                             # anything else → search (methods + types + tool metadata), scope-annotated;
                                             # response char-capped, truncations name the follow-up call (§3.2)
run <typescript source>                      # THE interface. Fast-pathed if call-shaped; sandboxed otherwise.
                                             # Read-only → output directly. Mutating → plan + plan-id.
apply <plan-id>                              # execute a confirmed plan (three-word id, §3.6.4)
sql <hogql>                                  # sugar for client.query.sql(...) via the fast path
```

- **`types` absorbs `search`, `info`, and `schema`.** The index searches full tool metadata including legacy tool names, so `types feature-flag-update` still resolves. `info`/`schema` were mitigations for JSON Schema verbosity; TS declarations are the systemic fix (§3.5). During migration, `info X` / `schema X [path]` / `search q` alias to the `types` renderings with a one-line deprecation note (drill-down paths are ignored — follow named types instead).
- **`sql` is the one concession to non-TS syntax.** HogQL inside a TS template literal inside a JSON string is three escaping layers, and the breaking layer (backticks/`${}`) breaks silently. HogQL is still code; the verb is implementation-wise a pre-parsed fast path into `client.query.sql()` that preserves the `execute-sql` prompt template and TOON output.
- **Hidden compatibility layer.** `call`, `info`, `schema`, `tools`, `search` keep working but disappear from `unknownCommandError`, all templates, and the tool blurb; each response gains a footer with the exact `run` equivalent (the fast-path resolver can generate it — in-context teaching) and emits deprecated-verb analytics. The Rust CLI vendors the dispatcher at build time, so released binaries keep legacy verbs regardless; server-side removal follows the §4.6 criteria, except `call` which stays indefinitely (SSE tools, CLI, ~50 lines).
- **The honest exception:** SSE-backed tools (session-recording summarization) have no SDK counterpart (§3.7) and stay reachable via `call`, annotated as such in `types` results.
- **Escaping escape hatch:** an optional `script` parameter on the exec input schema (`{command: "run", script: "…"}`) removes the TS-inside-JSON-string escaping problem for weak harnesses at ~200 chars of budget. Recommended.

Confirmation as implemented: a mutating fast-path script returns a one-entry plan + the same single-use plan id, and `apply` branches on plan kind (script → sandbox enforce pass; single call → direct handler dispatch), refusing either kind when the active project changed since the plan was minted.
`call` keeps its `--confirm` destructive gate and dispatches directly — it only gains the deprecation footer — so `call --confirm` dies with the verb itself, not before; unifying `call` onto plan/apply remains open.
Policy tiering per §3.6.7 still applies (org-level auto-apply for non-destructive creates).

### 4.4 Discovery decoupling and the instructions rewrite

**Decouple discovery from the executor.** The discovery index is a static artifact, but `resolveCodeExecutionRuntime` originally gated it together with the executor — an accident of wiring, since split: `types` (plus the aliases and `sql`) ships to 100% of single-exec clients on the flag alone, and `run`/`apply` dispatch everywhere the flag is on — the fast path (§4.2) serves call-shaped scripts even where no executor exists, while sandbox-requiring scripts there get a targeted redirect instead of an unknown command, with the instructions (`full` vs `fast-path` script sections) matching each process's actual execution capability.
TS-first discovery is a pure win independent of the sandbox timeline.

**Instructions collapse to one modality.** Today's `command` reference spends ~4–5 K chars on rules that compensate for JSON-schema guessing (the MANDATORY info-before-call block, the schema-drill-down protocol, the policing bad-examples).
Cut: `cli-schema-drilldown.md`, `tool-search.md`, `schema-workflow.md` (tool-inspection parts), `cli-syntax.md`, most of `cli-examples.md`/`examples.md` — roughly 12–13 K reclaimed.
Spend ~10–11 K on: a verb table + script contract section; **a generated cheat sheet of the top ~25 SDK method signatures by usage** (the highest-leverage addition — makes the common 80% of operations zero-discovery, one memorized one-liner instead of today's mandatory `info` round trip); a plan/apply protocol section; a discovery section; an `sql` section; and three worked transcripts (discovery → read, fast-path read, bulk mutation → plan → apply).
Net target ~22–24 K serialized — comfortable headroom under the 32,600-char claude.ai cap, with the budget test unchanged and enforcing.
Data-taxonomy prose (`cli-data-discovery.md`, verify events/properties before analytics) survives untouched: it is orthogonal to API-surface discovery and applies identically to `sql`, fast-path queries, and scripts.

### 4.5 Execution ergonomics

Judged by one metric: round trips × tokens × failure probability per completed task.
In current-impact order (the first four fix defects observed in live use):

1. **Result handles.** Every successful `run` stores its full untruncated `export default` server-side (Redis, same infra as the plan store; sliding TTL, per-session cap). The 48 K truncation message becomes a pointer (`results get last --path flags --offset 0 --limit 50`) instead of a dead end that forces a full re-run; `run --into <name>` names a handle; `results.get<T>('name')` reads one inside a later script (a GET through the transport, classified as a read). Kills the worst loop in the current design: truncation → rewrite → re-run.
2. **Runtime-error dossier.** Today errors return only `error.message`. Add: source-line mapping through the CJS rewrite (it preserves statement text verbatim, so the mapping is cheap), a ring buffer of the last ~5 API calls (body excerpt for non-2xx — the Django validation error is exactly what fixes a 400 one-shot; a keys+types shape sketch for 2xx), inlined relevant type declarations on TS2339/TS2345 compile errors (recovery in 1 round trip instead of error → `types` fetch → fix), a diagnostics cap (~10), and a `--timeout` flag (≤120 s) whose timeout message names the in-flight call.
3. **Plan rendering.** `renderPlanText` already supports `currentObjects` diffs but nothing passes them — hence the observed `UPDATE feature flag #0 (name: )` for a rollout-only PATCH. Wire a plan-pass read cache + targeted GETs (capped) so updates render `rollout: 50 → 100` with the current object's display name; aggregate bulk plans by (objectType, operation, changed-field set) with samples — deletes always enumerate; substitute sentinel values in provisional output with `<id of new feature_flag #2 — assigned on apply>` instead of leaking `-900001`; receipts return real created ids + app URLs. `plan show <token> [--page N]` reads the stored plan without re-planning.
4. **Discovery polish.** Worked examples + named recipes (`types recipe:<name>`, full runnable scripts with `// EDIT:` markers) in the index build; explicit `⚠ response is untyped — probe first` warnings on the ~86 `Promise<unknown>` methods (the §3.2 serializer-enrichment workstream remains the real fix). (The earlier BFS-ordering and `--budget`/`--brief` ideas are moot under the lean fetch contract in §3.2 — agents pull exactly the types they name.)
5. **`client.taxonomy.*`.** Promote `read-data-schema` into the SDK (`taxonomy.events/properties/propertyValues`) so event/property verification fuses into the analytics script itself — the verified-query pattern in one round trip, with self-reporting failure ("no event matching 'signup' — candidates: …"). Today this is a `call`-only tool and a forced modality switch.
6. **Latency tiers.** The plan pass is side-effect-free by construction (mutations never leave the process), so its security requirement is host isolation, not effect isolation: run every plan pass on cheap warm single-run-scoped workers (fresh fork per run, credential-poor, transport-pipe-only egress; target <500 ms), and reserve Modal for the post-confirmation `apply` pass where 5–15 s hides behind the human reading the plan. Converts the §3.7 warm-pool line from launch blocker to optimization. The `SandboxExecutor` seam already supports two executors (`planExecutor`/`applyExecutor`).
7. **`--trace`.** Opt-in per-run API-call log (method/path/status/latency/size + rate-limit headroom), auto-abbreviated on error. The same transport wrapper implements the error dossier's ring buffer **and** the per-underlying-API-call `$mcp_tool_call` analytics §3.4 already calls for — one seam, three consumers; build it first.

### 4.6 Rollout

**Phase 0 — analytics (no behavior change).** You cannot deprecate what you cannot measure, and today `types`/`run`/`apply` collapse into the `exec` bucket of `$mcp_tool_call` with no verb dimension. Add: `$mcp_exec_verb`, run status (`run`: `compile_error | read_only | plan_issued | failed | sandbox_unavailable`; `apply`: `applied | already_applied | not_found | diverged | failed` — expiry reports `not_found`, since single-use consumption cannot distinguish an expired id from a mistyped one), plan mutation count, fast-path hit flag, deprecated-verb flag; attribute fast-pathed runs to their inner tool exactly like `call` (dashboard continuity). Then answer empirically: what fraction of `call` traffic is fast-path-shaped (prior: ≥85%), and per-harness compile-error rates.

**Phase 1 — fast path + discovery decoupling.** Production-safe pre-Modal (§4.2). `sql` verb, `query.sql()` + `taxonomy.*` SDK methods, `types` aliases for `info`/`schema`/`search`. The CLI local execution mode (§4.8) ships in parallel with Phases 0–1 — it shares no infrastructure with the hosted rollout and unblocks coding-agent code exec immediately.

**Phase 2 — ergonomics core.** Transport wrapper (dossier + trace + per-method analytics), result handles, plan-rendering fixes. Pays off regardless of which surface wins.

**Phase 3 — code-first instructions behind a separate `mcp-code-first` flag,** independent of `mcp-code-execution` so the instruction flip can trail the runtime. A/B per organization against the current surface on: task completion proxy, tokens per session, error-loop depth, discovery-calls-before-first-success, fast-path hit rate, per-harness compile-error rate. Legacy verbs go hidden with deprecation footers in the code-first arm. Per-consumer instruction variants (client-profile machinery exists) are the escape valve for harnesses that measurably can't write escaped TS — not a global `call` resurrection.

**Phase 4 — sandbox GA and deprecation.** Modal for `apply` (per the §4.5 tier split), warm workers for plan passes. Remove a hidden verb when 30-day usage is <0.5–1% of exec calls and skills/evals/playbooks show zero references; `call` stays.

Maps onto §3.8: Phase 0–1 land inside Phase A/B; Phase 3 is the surface half of Phase C; Phase 4 aligns with C/D.
Tools-mode roster clients are untouched throughout (they register per-tool and never see verbs; the fast path _is_ their handlers, so nothing can be deleted from under them).

### 4.7 Risks specific to the redesign

- **Weak code-gen harnesses** — the hardest one. Multi-line escaped TS in a JSON string is strictly harder than `call tool {json}` for small models. Mitigations: the cheat sheet (common case = memorized one-liner), the `script` parameter, deprecation footers that print the exact `run` equivalent, per-consumer variants. The Phase 3 A/B is the arbiter; if a harness roster fails, it gets a variant, not a surface revert.
- **Nearly-call-shaped fallthrough** — agents write `limit: 2+1` or a variable and silently pay the sandbox. Measure fast-path hit rate per harness from day one; widen only with evidence and never past literal folding.
- **Two dispatch stacks drifting** — fast path → MCP handler (filtered, TOON) vs sandbox → SDK → proxy (full objects). Same method, different response shape. Document ("scripts see full API objects"); converge handlers onto the SDK (§2.8 step 2) as the structural fix.
- **Compile-gate strictness vs weak response types** — until the serializer-enrichment workstream lands, agents blocked by `unknown`-typed fields will cast to `any`; treat `any`-casts as warnings, not rejections, in the interim.
- **Instruction-budget regression** — every section swap re-runs the budget test; keep ≥2 K slack under 32,600.
- **Discovery long tail** — agents that found obscure tools via `search` must find them via `types`; the index searches a superset of `search`'s fields so this should be neutral or better, but verify with the types→run funnel before Phase 4 deprecations.

### 4.8 Local execution mode (CLI) — Phase A made concrete

The §3.8 Phase A line ("`posthog-cli api run` for local/trusted execution") and the §3.6.7 CLI-parity requirement become a concrete design: the code-exec verbs (`types` / `run` / `apply`) ship in the API CLI (`posthog-cli api …`, which already embeds the same `createExecTool` dispatcher), executing scripts **in-process on the user's machine**.
This is the fastest route to production code execution for the dominant consumer segment (coding agents), and it has **no Modal dependency**.

**Trust model.**
The hosted sandbox exists because hosted agent scripts are untrusted code running on PostHog's infrastructure next to other tenants' credentials.
On the user's own machine neither concern applies: the only credential a script could exfiltrate is the user's own key, already in their env, and coding-agent harnesses (Claude Code, Cursor) already execute arbitrary shell commands there — the harness's permission system is the security boundary, exactly as for every other local tool.
The executor's forced transport is kept anyway as a prompt-injection mitigation: `createClient` is force-wrapped so `fetch`/`host`/`apiKey` cannot be overridden and only `@posthog/sdk` resolves, so even a steered script cannot talk to anything but the PostHog API.
The `node:vm` wrapper is a convenience seam here, not a security boundary — and locally it doesn't need to be one.

**The distribution constraint that shapes the design.**
The distributed CLI is a single esbuild bundle (built from `services/mcp`, embedded into the Rust `posthog-cli` via `cli/build.rs`, materialized to `~/.posthog/api-cli/<version>/posthog-api-cli.mjs`, and executed by the system `node`) with **no `node_modules` beside it** — bundle-external packages are unresolvable at runtime.
Consequences:

- **Script lowering unifies on sucrase (all environments).** The executor's current lowering (TypeScript-AST module rewrite + esbuild `transform`) depends on two bundle-external packages and can never run in the distributed CLI. It is replaced everywhere by sucrase (`transforms: ['typescript', 'imports']` — pure JS, inlined into every bundle), with the CJS output wrapped in one async IIFE for top-level await. One lowering path for server dev, tests, and CLI; `esbuild` leaves the runtime path entirely.
- **The compile gate becomes an injected dependency of the runtime.** The server injects the real `ts.LanguageService` gate (`typescript` stays bundle-external there; node_modules exists on the server image and in dev). The CLI injects none — keeping `typescript` and the ~4.3 MB `SDK_DTS` artifact out of the bundle — and falls back to the two contract lints (no `require(`; must `export default`) plus runtime errors, noting that the typecheck was skipped. The discovery index (~4 MB) and classifier table do ship in the CLI bundle: `types` and plan classification work fully offline from the API.
- **Plan/apply must survive process exit** (the CLI is one-shot per invocation). Plan records live as files under `~/.posthog/code-exec/` (respecting `$POSTHOG_HOME`, the Rust CLI's existing home-dir convention), keyed by the three-word plan id (§3.6.4 — filename-safe by construction), with the same TTL and single-use semantics as the hosted path: `run` prints the plan + id, a later `apply <plan-id>` invocation loads and enforces it, consumption leaves a tombstone file so reuse and expiry are rejected identically. No signing key and no nonce ledger — the §3.6.4 revision removed both from code exec.

**Executor gating.**
`LocalVmExecutor` keeps its fail-closed `NODE_ENV` check; the CLI passes an explicit `trustedLocal` opt-in that only the CLI entrypoint sets.
The hosted server path is unchanged and still refuses local execution outside development/test.

**CLI surface.**
Same verbs, same contracts as the hosted exec tool, plus file ergonomics (inline TS in argv is quoting hell for agents): `run --file <path>` and `run -` (stdin), and `--yes` to apply a plan in the same invocation for scripted/CI use (§3.6.7's knob).
`types` works without an API key (static index); `run`/`apply` require one.
Analytics parity: the CLI emits verb-labelled `$mcp_tool_call` events with its existing `$mcp_mode: 'cli'` / `$mcp_consumer: 'posthog-cli'` stamps, so local code-exec adoption lands in the same dashboards as the hosted verbs (§4.6 Phase 0).

**Boundaries.**
No Rust-side changes are required (credential env injection and bundle embedding already suffice).
A locally-distributed stdio MCP server is deliberately **not** part of this: MCP distribution stays remote-first; the CLI is the local execution channel, and a local MCP wrapper is reconsidered only if agents fluent in `exec run` measurably fail to adopt the CLI invocation path.
Version skew is bounded by the existing bundle-vendoring cadence — the discovery index and classifier in a released CLI are as fresh as that release, which is acceptable for a surface that fails soft (an unknown method errors with a search hint; the API remains the source of truth for validation).
