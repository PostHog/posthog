# Design — runtime `spec.mcps[]` support

**Status:** draft / open questions. **Owner:** ben. **Tracking:** TODO C6 in `services/agent-shared/TODO.md`.

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

1. **Schema alignment (no runner changes).** Add `id` + `secrets[]` to the
   `external` variant, mirror into the console's hand-rolled types, update
   `spec.test.ts`, refresh this plan. _← this PR._
2. **`loop/mcp-clients.ts`.** Client-open helper using
   `@modelcontextprotocol/sdk`'s `Client` + `StreamableHTTPClientTransport`.
   Resolves auth per variant. Unit tests with `InMemoryTransport`.
3. **Wire into `buildAgentTools`.** Add an `mcpClients` field to
   `AgentToolDeps`, append MCP tools after the existing loop, add a
   `provider-safe-names-coverage.test.ts` fixture for `<id>__<name>`.
4. **Worker lifecycle.** Open + close clients in `worker.runOne`'s
   try/finally, thread the map through `RunSessionDeps`.
5. **e2e harness coverage.** `mcp-tools.test.ts` spins up an in-process
   `McpServer`, drives an agent that calls into it.
6. **`kind: 'agent'` variant.** Resolve the URL via the local revision store,
   mint `posthog_internal`. Unblocks the concierge example by dropping the
   `spec["mcps"] = []` strip in `scripts/seed.py`.

## What this unblocks

- Agents that need tools we don't ship natively (e.g. Linear, GitHub).
- The agent-as-mcp-server work (`agent-as-mcp-server.md`) — the `kind: 'agent'`
  variant is the runtime consumer of that plan's `/agents/<slug>/mcp` endpoint.

## Out of scope

- Streaming tool results from MCPs (one-shot only for v1).
- MCP sampling (the MCP-defined "ask the model" pattern). pi-ai handles all
  inference for now.
- Self-hosted MCP gateway / quota management.
- Per-MCP-tool approval policies. The concierge bundle declares these via an
  `approval_policies` field per MCP; the schema doesn't accept it yet.
  Track with the schema-flattening work above.
