# Design — runtime `spec.mcps[]` support

**Status:** PRs 1-6 landed; PR 7 (prod resolver + concierge unblock) pending. **Owner:** ben. **Tracking:** [`_ROADMAP.md`](_ROADMAP.md) §C.2.

## Problem

`AgentSpec.mcps[]` is already in the schema but the runner doesn't read it. The
intent: an agent author lists third-party MCP servers their agent can call
into; the runner opens MCP clients to each one at session start, exposes each
remote tool to pi-ai as a regular `Tool`, and routes the dispatch back through
the open client when the model calls it.

## Spec shape (currently in code)

The spec lives in `services/agent-shared/src/spec/spec.ts` as a discriminated
union — NOT the flat `{ id, endpoint, tools[], secrets[] }` shape an earlier
draft of this plan described. The union exists because the platform supports
two MCP-source kinds and they need different fields:

```typescript
McpRefSchema = z.discriminatedUnion('kind', [
  // Agent-to-agent over MCP. Points at another PostHog agent's MCP trigger
  // on the same control plane. Auth piggybacks on `posthog_internal`; the
  // runner resolves the URL from the local revision store. See
  // `agent-as-mcp-server.md` §9 for the composability story.
  z.object({
    kind: z.literal('agent'),
    slug: z.string(), // doubles as the tool-name prefix
  }),
  // Third-party MCP server reachable over HTTP.
  z.object({
    kind: z.literal('external'),
    id: z.string().min(1), // tool-name prefix at runtime
    url: z.string().url(),
    auth: z
      .object({
        // OAuth-style via PostHog integrations
        integration: z.string().optional(),
      })
      .optional(),
    secrets: z.array(z.string()).default([]), // simple per-MCP tokens
    allowlist: z.array(z.string()).optional(), // empty/omitted = expose all
  }),
])
```

**Future migration (not blocking — track as a follow-up).** The longer-term
shape we want is closer to what the concierge example bundle declares:
`{ id, endpoint, tools[], secrets[] }` with no discriminator and an
`approval_policies?: Record<toolName, ApprovalPolicy>` field for destructive
remote tools. We're holding the union for now because:

- the console (`ConnectionsTab.tsx`, `ConfigPanel.tsx`) already renders against
  the `kind` discriminator,
- `spec.test.ts` exercises both variants,
- the `agent` variant's URL resolution + `posthog_internal` auth flow has
  enough divergence from the external case that a discriminator is honest.

Flattening should happen alongside the v2 work that adds per-MCP-tool approval
policies — the schema change is too disruptive to do in isolation. When we
revisit, the `agent` variant becomes `{ id: slug, endpoint: '<resolved
internal URL>', secrets: [], allowlist: undefined }` and the discriminator
disappears.

## Runner integration sketch

`run-turn.ts` (or a new `loop/mcp-clients.ts`) opens an MCP client per entry
at session start, alongside the existing custom-tool sandbox acquire:

```typescript
const mcpClients: Map<string, McpClient> = new Map()
const decls: AgentTool[] = []
for (const mcp of rev.spec.mcps) {
  const { prefix, transport, headers } = await resolveMcpTransport(mcp, deps)
  // `prefix` is `mcp.slug` for `kind: 'agent'`, `mcp.id` for `kind: 'external'`.
  const client = await openMcpClient(transport, headers)
  mcpClients.set(prefix, client)
  const tools = await client.listTools()
  for (const tool of tools) {
    if (mcp.kind === 'external' && mcp.allowlist?.length && !mcp.allowlist.includes(tool.name)) {
      continue
    }
    // Add to the tool list pi-ai sees, name-prefixed so callers can tell
    // which MCP a tool comes from + the runner can route the dispatch back.
    const exposedName = `${prefix}__${tool.name}`
    decls.push({
      name: exposedName,
      description: tool.description,
      parameters: tool.inputSchema,
      execute: async (_callId, args) => {
        const result = await client.callTool(tool.name, args)
        return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { output: result } }
      },
    })
  }
}
```

Tool dispatch is per-tool (each `AgentTool.execute` closes over its client),
so there's no central prefix-routing table to maintain — the prefix is purely
a model-facing disambiguator.

Lifecycle:

- `acquire` (open clients) → `runSession` → `release` (close clients) in the
  Worker's `try/finally` at `services/agent-runner/src/workers/worker.ts`,
  alongside the existing sandbox release.
- Crash semantics same as sandboxes: drop the client, mark session failed.

## Auth resolution

- **`kind: 'agent'`** — the runner looks up the target agent by `slug` in the
  same team's revision store, builds the URL the ingress serves at
  `/agents/<slug>/mcp` (path mode locally, `<slug>.agents.posthog.com` in
  prod), and authenticates with `posthog_internal`. No author-visible token.
- **`kind: 'external'`, `auth.integration`** — read the integration record
  (`integrations[ref]`), extract its bearer/oauth token, stamp into the
  Authorization header.
- **`kind: 'external'`, `secrets[]`** — resolve each secret name through the
  same encrypted-env path as `spec.secrets`. The resolver substitutes
  `${SECRET_NAME}` placeholders inside `url` + any author-supplied headers
  before opening the transport. Plaintext never leaves the runner process.

## Security floor for `external` URLs

The author-supplied `url` on a `kind: 'external'` MCP ref is treated as
untrusted input. Before opening the transport, the runner enforces:

- **HTTPS only.** `http://`, `ws://`, `file://`, etc. are rejected with
  `mcp_unsafe_url: scheme must be https`.
- **Private / loopback / cloud-metadata hostnames are rejected.** IPv4
  loopback (`127.0.0.0/8`), RFC1918 (`10.0.0.0/8`, `192.168.0.0/16`,
  `172.16.0.0/12`), link-local (`169.254.0.0/16`, includes AWS/GCP/Azure
  IMDS), `localhost`, IPv6 loopback / unique-local / link-local, and
  hostnames ending in `.local` or `.internal` all fail at open with
  `mcp_unsafe_url: hostname '<h>' is private / loopback / link-local`.
  Lives in `assertSafeExternalMcpUrl` in `loop/mcp-clients.ts`.
- **Integration bearer attachment is fail-closed.** When `auth.integration`
  is set, the runner consults `WorkerDeps.integrationHostValidator` —
  `(integrationRef, url) => boolean` — before stamping the bearer header.
  Without a wired validator (config drift, deploy issue), every such
  request is refused (`mcp_integration_host_validator_not_wired`). With
  one wired but the URL host outside its allowlist, the request is
  refused with `mcp_integration_host_not_allowed`. Production wires a
  per-integration-kind registry (`linear:*` → `mcp.linear.app`,
  `github:*` → `api.github.com`, etc.); v0 tests pass `() => true` to
  opt in to the legacy "attach-to-anywhere" behaviour.

`kind: 'agent'` URLs are minted by the runner's own resolver — not author
input — and don't pass through `assertSafeExternalMcpUrl`.

**Known gap (DNS rebinding).** The hostname checks are string-pattern
only; a public hostname that A-records to a private IP slips through.
Closing that requires a custom HTTP agent that resolves DNS and inspects
each candidate IP before connect. Tracked as a follow-up.

## Open questions (and what's now known)

1. **Auth model.** ~~Punt OAuth to v2.~~ The schema already accepts both
   `auth.integration` (OAuth-style) and `secrets[]` (simple token). v1 wires
   both paths; what's deferred is _new_ integration kinds.
2. **Name collision strategy.** ~~Could elide the prefix when only one MCP
   exposes a given name.~~ Keep verbose + prefix everything: the surface
   shouldn't depend on what's configured. The model sees `posthog__list-agents`
   and `github__list-issues`; the description tells it which service the tool
   belongs to.
3. **Provider-safe name interaction.** Confirmed safe. `provider-safe-names.ts`
   flattens `@` / `/` / `.` to `_`; `__` is already in the safe set. The new
   coverage test in PR 3 pins this with an MCP-prefixed fixture.
4. **Latency.** Opening N MCP clients at session start adds N round-trips.
   Open in parallel (`Promise.all`); revisit a `(team_id, endpoint)` connection
   pool only if p99 measurements show it matters.
5. **What happens when an MCP is down mid-session?** Surface a `tool_result`
   error to the model. The model can retry, ask the user, or `end_session`.
   We do NOT auto-fail the whole session. (Pre-existing
   `AgentTool.execute → throw → loop renders error tool_result` path handles
   this with no extra work.)
6. **Discovery.** Free-form URLs for v1 (advanced users). A curated marketplace
   is a follow-up that piggybacks on the template library
   (`agent_mcp_template`). The `kind: 'agent'` variant is the in-platform
   shortcut — the curated case is "your team already authored another agent."

## Testing strategy

- **Unit** — name prefixing, allowlist filtering, dispatch routing
  (`build-agent-tools.test.ts`, plus a new `mcp-clients.test.ts`).
- **Integration / e2e** — spin up a tiny `McpServer` in-process using
  `@modelcontextprotocol/sdk` (same pattern as
  `services/mcp/tests/integration/mcp-protocol-suite.ts`), point an agent's
  `mcps[]` at it, prove the round-trip works through `runSession`. Lives in
  `services/agent-tests/src/cases/mcp-tools.test.ts`.
- **Real-inference variant** — optional, gated like the existing
  `real-inference.test.ts`. The faux provider is enough to prove dispatch
  routing; real-inference proves the model can actually use a prefixed tool.

## Implementation rollout

Split across discrete PRs so each is reviewable in isolation:

1. **Schema alignment (no runner changes).** ✅ Added `id` + `secrets[]` to
   the `external` variant, mirrored into the console's hand-rolled types,
   updated `spec.test.ts`, refreshed this plan.
2. **`loop/mcp-clients.ts`.** ✅ Client-open helper using
   `@modelcontextprotocol/sdk`'s `Client` + `StreamableHTTPClientTransport`.
   Resolves auth per variant. Unit tests with `InMemoryTransport`.
3. **Wire into `buildAgentTools`.** ✅ Added an `mcpClients` field to
   `AgentToolDeps`, appended MCP tools after the existing loop, added a
   `provider-safe-names-coverage.test.ts` fixture for `<id>__<name>`.
4. **Worker lifecycle.** ✅ Opens + closes clients in `worker.runOne`'s
   try/finally, threads `mcpClients` through `RunSessionDeps`.
5. **e2e harness coverage.** ✅ `mcp-tools.test.ts` spins up an in-process
   `McpServer`, drives an agent that calls into it.
6. **`kind: 'agent'` resolver contract.** ✅ Added `AgentMcpResolverContext`
   (`{ teamId, sessionId }`) so the resolver can enforce team isolation.
   Worker forwards it from the session. e2e cases prove the URL is built
   from `ctx.teamId` and that a missing resolver fails the session loudly.
7. **Prod resolver wiring + concierge unblock.** _Pending._ The runner now
   has the seam; the prod entrypoint needs to construct a default
   `AgentMcpResolver` (revision lookup + ingress URL + `posthog_internal`
   bearer) and wire it via `WorkerDeps`. Once that lands, the concierge
   example can drop its `spec["mcps"] = []` strip — but the strip is _also_
   load-bearing for two other gaps (the concierge spec uses the flat
   `{ id, endpoint, tools[], secrets[] }` shape this plan tracks as a v2
   migration, and declares `approval_policies` per-MCP-tool which the
   schema doesn't accept yet). All three need to land together; see the
   "Out of scope" notes below.

## What this unblocks

- Agents that need tools we don't ship natively (e.g. Linear, GitHub).
- The agent-as-mcp-server work (`agent-as-mcp-server.md`) — the `kind: 'agent'`
  variant is the runtime consumer of that plan's `/agents/<slug>/mcp` endpoint.

## Out of scope

- Streaming tool results from MCPs (one-shot only for v1).
- MCP sampling (the MCP-defined "ask the model" pattern). pi-ai handles all
  inference for now.
- Self-hosted MCP gateway / quota management.

## Open design — per-MCP-tool approval gating

**Unresolved alignment between `ToolRefSchema` and `McpRefSchema`.** Native and
custom tools today express per-invocation approval via
`ToolRef.requires_approval` + `ToolRef.approval_policy` (see
[`approval-gated-tools.md`](approval-gated-tools.md) §3). MCP tools don't have
a static `ToolRef` to hang the flag on — they materialise at session start from
`client.listTools()`. The concierge example bundle invented an
`approval_policies: Record<remoteName, ApprovalPolicy>` field on each MCP entry;
the schema doesn't accept it.

Two designs in play; both deferred until the concierge unblock (PR 7) forces
a choice:

- **Option A — `mcps[].tools[]` as a list of objects.** Replace `allowlist[]`
  with a `tools[]` field that accepts either a bare tool name (passthrough) or
  an object carrying optional `requires_approval` + `approval_policy`. Reuses
  `ApprovalPolicySchema` verbatim. Minimum disruption; doesn't unify with
  `ToolRef`. Concierge migration is mechanical.
- **Option C — top-level `spec.approvals.rules[]`.** Glob-matched against the
  fully-qualified tool name (`@posthog/team-delete` for native;
  `<prefix>__<remoteName>` for MCP). One surface for all gating. Bigger
  schema change. `ToolRef.requires_approval` becomes sugar.

The pragmatic call (made during PR 6 design discussion) was Option A first:
the concierge is the only customer today, the dispatcher change is contained
to `build-agent-tools.ts:makeMcpTool`, and Option A's per-entry shape desugars
cleanly into Option C's rules format later. Revisit Option C when a second
MCP-heavy use case (Linear / GitHub / SRE bot) lands and starts asking for
globs like `linear__*-delete`.

Adjacent gap: the concierge wants `approvers: ['session_principal']` — that
scope isn't in the v0 enum at all. Approver-scope expansion is a separate
B.2 v1 line item (see [`approval-gated-tools.md`](approval-gated-tools.md) §6)
and PR 7 needs to pull it forward.

Tracked from [`_TODO.md`](_TODO.md) "MCP tool approval gating — unresolved
schema alignment" and [`_ROADMAP.md`](_ROADMAP.md) §C.2 / §B.2.
