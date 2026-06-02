# Design — runtime `spec.mcps[]` support

**Status:** draft / open questions. **Owner:** ben. **Tracking:** TODO C6 in `services/agent-shared/TODO.md`.

## Problem

`AgentSpec.mcps[]` is already in the schema but the runner doesn't read it. The
intent: an agent author lists third-party MCP servers their agent can call
into; the runner opens MCP clients to each one at session start, exposes each
remote tool to pi-ai as a regular `Tool`, and routes the dispatch back through
the open client when the model calls it.

## Spec shape (already present)

```typescript
mcps: z.array(
  z.object({
    // Stable id within the agent — used as the tool name prefix
    id: z.string(),
    // ws:// or stdio:// or sse:// — the MCP transport
    endpoint: z.string(),
    // Optional: subset of tools to expose. Empty = expose them all.
    tools: z.array(z.string()).default([]),
    // Optional: per-MCP env (mostly auth tokens). Resolved via SecretBroker
    // at session start, same as the agent's main secrets.
    secrets: z.array(z.string()).default([]),
  })
)
```

## Runner integration sketch

`run-turn.ts` (or a new `loop/mcp-clients.ts`) opens an MCP client per entry
at session start, alongside the existing custom-tool sandbox acquire:

```typescript
const mcpClients: Map<string, McpClient> = new Map()
for (const mcp of rev.spec.mcps) {
  const client = await openMcpClient(mcp.endpoint, secrets[mcp.secrets])
  mcpClients.set(mcp.id, client)
  const tools = await client.listTools()
  for (const tool of tools) {
    if (mcp.tools.length > 0 && !mcp.tools.includes(tool.name)) continue
    // Add to the tool list pi-ai sees, name-prefixed so callers can tell
    // which MCP a tool comes from + the runner can route the dispatch back.
    const exposedName = `${mcp.id}__${tool.name}`
    decls.push({ name: exposedName, description: tool.description, parameters: tool.inputSchema })
  }
}
```

Tool dispatch checks the prefix; if it matches an MCP id, route to that
client's `callTool` instead of the native registry or the sandbox.

Lifecycle:

- `acquire` (open clients) → `runSession` → `release` (close clients) in the
  Worker's `try/finally`, alongside the existing sandbox release.
- Crash semantics same as sandboxes: drop the client, mark session failed.

## Open questions

1. **Auth model**: do MCPs use OAuth (per-team integration) or per-agent
   secrets? Both probably — `secrets[]` covers the simple case; OAuth needs
   to plug into PostHog's `integrations` framework. Punt OAuth to v2.
2. **Name collision strategy**: `<mcp_id>__<tool_name>` is verbose but
   unambiguous. We could elide the prefix when only one MCP exposes a given
   name — but that makes the surface depend on what's configured. Keep
   verbose + prefix everything; the description tells the model which
   service it's calling.
3. **Provider-safe name interaction**: our existing sanitizer
   (`provider-safe-names.ts`) flattens `@` / `/` / `.` to `_`. The MCP
   prefix uses `__` which is already safe. No interaction.
4. **Latency**: opening N MCP clients at session start adds N round-trips.
   For low-latency triggers (Slack) this could push p99 noticeably. Open
   in parallel; consider a connection pool keyed by `(team_id, mcp_endpoint)`
   in a follow-up if it matters.
5. **What happens when an MCP is down mid-session?** Today we'd surface a
   tool_result error to the model. That's probably right — the model can
   choose to retry, ask the user, or end_session. We should NOT auto-fail
   the whole session.
6. **Discovery**: should `spec.mcps[]` be free-form URLs, or do we have a
   pre-curated "PostHog MCP marketplace" of vetted endpoints? Free-form for
   v1 (advanced users); a curated list is a follow-up that piggybacks on
   the template library (`agent_mcp_template`).

## Testing strategy

- Unit: name prefixing, dispatch routing.
- Integration: spin up a tiny local MCP server in a test fixture, point an
  agent's `mcps[]` at it, prove the round-trip works through `runSession`.
- Real-inference variant: optional, gated like the existing
  `real-inference.test.ts`.

## What this unblocks

- Agents that need tools we don't ship natively (e.g. Linear, GitHub).
- The B5 MCP redesign can lean on this — the authoring MCP could be one of
  the listed MCPs an agent talks to.

## Out of scope

- Streaming tool results from MCPs (one-shot only for v1).
- MCP sampling (the MCP-defined "ask the model" pattern). pi-ai handles all
  inference for now.
- Self-hosted MCP gateway / quota management — covered separately by
  [`self-hosted-tool-runners.md`](self-hosted-tool-runners.md), which
  solves the _not-publicly-reachable_ MCP case (Grafana, k8s,
  internal-only APIs) via an outbound-poll runner the customer deploys
  in their own infra.
