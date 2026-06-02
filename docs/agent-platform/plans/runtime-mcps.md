# Design — runtime `spec.mcps[]` support

**Status:** PRs 1-6 landed (#61014); PR 7 in progress as a single PR with three
commits (schema → dispatcher → prod resolver + concierge unblock). **Owner:**
dylan. **Tracking:** [`_ROADMAP.md`](_ROADMAP.md) §C.2.

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
    // Per-tool selection AND per-tool approval policy. Bare string is a
    // passthrough (gates inclusion, no approval); object form adds the
    // requires_approval + approval_policy primitives from ToolRefSchema.
    // Omitted / empty = expose every tool the server lists. Replaces the
    // earlier `allowlist[]` field; the bare-string entry preserves its
    // semantics. See PR 7 commit A in the rollout below.
    tools: z
      .array(
        z.union([
          z.string().min(1),
          z.object({
            name: z.string().min(1),
            requires_approval: z.boolean().default(false),
            approval_policy: ApprovalPolicySchema.default(DEFAULT_APPROVAL_POLICY),
          }),
        ])
      )
      .optional(),
  }),
])
```

**Future migration (not blocking — track as a follow-up).** The longer-term
shape we want is closer to what the concierge example bundle originally
declared: `{ id, endpoint, tools[], secrets[] }` with no discriminator. We're
holding the union for now because:

- the console (`ConnectionsTab.tsx`, `ConfigPanel.tsx`) already renders against
  the `kind` discriminator,
- `spec.test.ts` exercises both variants,
- the `agent` variant's URL resolution + `posthog_internal` auth flow has
  enough divergence from the external case that a discriminator is honest.

PR 7's tools[] change (commit A) is deliberately compatible with this future
flatten: an `external` ref's `{ id, url, secrets, tools }` already matches the
flat shape; the `agent` variant becomes `{ id: slug, url: '<resolved internal
URL>', secrets: [], tools: undefined }` and the discriminator disappears.
Approval gating piggybacks naturally on the tools[] field that's already in
place.

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
    if (mcp.kind === 'external' && mcp.tools?.length) {
      const entry = mcp.tools.find((t) => (typeof t === 'string' ? t : t.name) === tool.name)
      if (!entry) continue
      // entry may be an object carrying requires_approval / approval_policy —
      // looked up by the dispatcher when wrapping the tool's execute. See
      // `mcp-tool-lookup.ts` and the approval-wrap path in `driver.ts`.
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

## Future direction: native OAuth discovery (suggested, not yet planned)

> Added as a review suggestion — not a commitment. The shape below is
> what a follow-up plan (`runtime-mcps-oauth-discovery.md`) should design,
> not what this plan ships.

The auth story today uses `Integration` rows for OAuth tokens, which works
but requires **per-MCP-server, hand-curated `OauthIntegration` kinds**
(the existing `oauth_config_for_kind` switch in
[`posthog/models/integration.py`](../../../posthog/models/integration.py))
— one PR per MCP server an agent wants to talk to, plus a per-kind
client_id/client_secret pre-registered with the target's auth server.

The MCP spec itself prescribes a cleaner path that every compliant MCP
server (and Claude Desktop / mcp-inspector / Cline) already implements:

1. The MCP server advertises its OAuth resource via
   `/.well-known/oauth-protected-resource` (RFC 9728). Tells you which
   auth server to use, supported scopes, resource metadata.
2. The auth server advertises its endpoints via
   `/.well-known/oauth-authorization-server` (RFC 8414).
3. The client **dynamically registers** with the auth server via
   `/oauth/register` (RFC 7591 — Dynamic Client Registration). No
   pre-shared `client_id`/`client_secret` needed.
4. Standard PKCE-protected authorization-code flow, refresh tokens,
   etc.

This is how your local PostHog MCP "just worked" in Claude Desktop without
PostHog shipping a Claude-specific integration kind. PostHog itself is on
both sides of this protocol: it's an OAuth resource server (for inbound
MCP calls) and could be an OAuth client (for outbound MCP refs in agent
specs).

**What's already in the Django side that would be reused:**

- DCR endpoint at [`posthog/api/oauth/dcr.py`](../../../posthog/api/oauth/dcr.py) — already provider-side, but the
  _client_ side of DCR (POSTing to a remote auth server's `/register`) is
  the symmetric thing this would need.
- The `Integration` row + encrypted `sensitive_config` for storage.
- `OauthIntegration.access_token_expired()` + `refresh_access_token()`
  pattern — generalisable past the per-kind switch.
- `IntegrationViewSet` callback handling at `/integrations/<kind>/callback`
  — could be parametrised over the MCP server's resource URL.

**Sketch of the missing piece** — a sibling `McpOauthIntegration` class
(or generic `DiscoveredOauthIntegration`) that:

- Accepts an MCP server URL as input rather than a hand-curated `kind`.
- Fetches the two `.well-known/` documents at connect time.
- Performs DCR against the discovered auth server, stores the resulting
  `client_id`/`client_secret` on the integration row alongside the
  access/refresh tokens.
- Manages the redirect flow the same way `OauthIntegration` does but
  with the dynamically-discovered `authorize_url` / `token_url`.
- Reuses `access_token_expired` / refresh / storage unchanged.

**Per-asker scoping (Level C in the discussion that produced this section).**
Today an `Integration` row is keyed `(team, kind, integration_id)` — team-
scoped, one token per team. For per-asker auth into an MCP server (so a
GitHub MCP call goes as the specific session principal, not as the
team), the storage shape needs `(team, kind, user_id, integration_id)`.
That's a separable follow-up to discovery itself, but probably worth
designing alongside since both compose with the per-asker authorisation
model from [`per-session-access-elevation.md`](per-session-access-elevation.md).

**Why this is suggested, not in scope here:** the current plan
intentionally ships the storage seam (`auth.integration`) so that
_either_ hand-curated kinds _or_ a future discovery layer can populate
it. PR 7's runner code reads `cred.access_token` from an `Integration`
row without caring how it got there. Landing discovery is purely
additive — no spec change, no runner change — which is why it's a
follow-up rather than a v0 blocker.

A `runtime-mcps-oauth-discovery.md` plan should cover: the DCR client
implementation, the well-known-discovery cache, per-asker scoping
storage, the UI flow for "Connect an MCP" without per-kind plumbing, and
the security-review delta (untrusted auth-server URLs surfacing through
discovery need their own validation).

## Open questions (and what's now known)

1. **Auth model.** ~~Punt OAuth to v2.~~ The schema already accepts both
   `auth.integration` (OAuth-style) and `secrets[]` (simple token). v1 wires
   both paths; what's deferred is _new_ integration kinds. See the new
   §"Future direction: native OAuth discovery" — the suggestion is that
   instead of growing the per-kind switch case-by-case, a follow-up plan
   designs a generic discovery + DCR layer that reads any compliant MCP
   server's `.well-known/oauth-protected-resource` and registers
   dynamically. PostHog already has DCR on the provider side, so the
   missing piece is the client side.
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

- **Unit** — name prefixing, tools[] filtering (with both bare-string and
  object entries), dispatch routing, approval-wrap fallback for MCP tools
  (`build-agent-tools.test.ts`, `driver.test.ts`, plus a new `mcp-clients.test.ts`
  and `mcp-tool-lookup.test.ts`).
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
7. **Prod resolver wiring + concierge unblock + per-MCP-tool approval gating.**
   _In progress._ Lands as a single PR with three sequential commits so the
   shape is reviewable in isolation but the concierge proves the whole
   thing end-to-end in one merge:
   - **Commit A — schema.** Replace `external.allowlist[]` with `tools[]`
     (string | object, object form carrying `requires_approval` +
     `approval_policy`). Widen `ApprovalPolicySchema.approvers` to add
     `session_principal`. Mirror in Django `spec_schema.py`. Regen
     OpenAPI (`api.zod.ts`, `api.schemas.ts`). Update the console's
     hand-rolled `types/mcp.ts` + the `ConnectionsTab` / `ConfigPanel`
     render paths. Extend `spec.test.ts`.
   - **Commit B — dispatcher + approval-wrap fallback for MCP tools.**
     New `loop/mcp-tool-lookup.ts` helper that decomposes
     `<prefix>__<remoteName>` against `spec.mcps[]` to find the per-tool
     approval policy. `build-agent-tools.ts` swaps the `allowlist`-based
     filter for a `tools`-based one. `driver.ts:323-374` adds a
     `lookupMcpToolApproval` fallback after the `spec.tools.find` lookup.
     `per-asker-auth.ts` gains a `session_principal` branch that compares
     against `session.principal` (the auth-time identity stored on the
     row), not last-sender — so a second user posting to a resumed
     session can't bypass the gate. Driver test + e2e in `mcp-tools.test.ts`.
   - **Commit C — prod resolver + concierge unblock + e2e proof.** New
     `resolvers/agent-mcp-resolver.ts` (revision lookup + ingress URL +
     `x-posthog-internal` header from `INTERNAL_SECRET`). Wired in
     `index.ts` behind `AGENT_INGRESS_BASE_URL` + `INTERNAL_SECRET`;
     skipped with a warn (`agent_mcp_resolver_disabled`) when either is
     unset so dev / CI boots cleanly. Rewrite the concierge `spec.json`
     `mcps[]` from flat → `kind: 'external'`, with `tools[]` carrying
     `approval_policy.approvers: ['session_principal']` on the
     destructive tools. Delete the `spec["mcps"] = []` strip in
     `seed.py`. E2E case proves a concierge-loaded gated MCP tool queues
     an approval row instead of running.

## What this unblocks

- Agents that need tools we don't ship natively (e.g. Linear, GitHub).
- The agent-as-mcp-server work (`agent-as-mcp-server.md`) — the `kind: 'agent'`
  variant is the runtime consumer of that plan's `/agents/<slug>/mcp` endpoint.

## Out of scope

- Streaming tool results from MCPs (one-shot only for v1).
- MCP sampling (the MCP-defined "ask the model" pattern). pi-ai handles all
  inference for now.
- Self-hosted MCP gateway / quota management.

## Resolved design — per-MCP-tool approval gating

Native and custom tools today express per-invocation approval via
`ToolRef.requires_approval` + `ToolRef.approval_policy` (see
[`approval-gated-tools.md`](approval-gated-tools.md) §3). MCP tools don't have
a static `ToolRef` to hang the flag on — they materialise at session start from
`client.listTools()`. The concierge example bundle originally invented an
`approval_policies: Record<remoteName, ApprovalPolicy>` field on each MCP
entry, which the schema didn't accept.

PR 7 closes the gap with **Option A — `mcps[].tools[]` as a list of strings
or objects.** The bare-string form is the old `allowlist[]` semantics; the
object form `{ name, requires_approval?, approval_policy? }` reuses
`ApprovalPolicySchema` verbatim. Concierge migration is mechanical (`spec.json`
rewrite). The shape desugars cleanly into the eventual
`spec.approvals.rules[]` glob form (Option C) when a second MCP-heavy use case
(Linear / GitHub / SRE bot) lands and asks for `linear__*-delete`-shaped
globs; tracking that as the next iteration.

**Locked decisions** (after PR-7 design pass):

- **A1: `external` only.** `tools[]` lands on the `external` variant. The
  `agent` variant keeps its bare-slug shape — the target agent owns its own
  approval gating via its own spec, so re-gating at the caller side is
  redundant.
- **A2: hard-break `allowlist[]`.** No deprecation shim. No production specs
  use it today; the only callers are inside the runtime-mcps PR set + the
  concierge bundle (rewritten in commit C).
- **A3: no `description` override yet.** One field at a time; revisit if a
  concrete use case shows up (e.g. concierge wants to relabel
  `agent-applications-revisions-promote-create` as "Promote draft to live").
- **B1: `session_principal` compares against `session.principal`** (the
  auth-time identity stored on the session row, stable across resume) — not
  `findLastUserSender(conversation)`. A second user posting to a resumed
  session must not bypass the gate.
- **C1: per-asker fast-path only for v0.** The `session_principal` approver
  scope is wired into `per-asker-auth.ts` so the session principal's own
  follow-up satisfies the gate without round-tripping through the approval
  queue. Surfacing a queued approval to that specific user via
  `/api/approvals` (so a different team admin doesn't have to ack a
  concierge-fired tool intended for the session principal) widens in a
  follow-up — tracked in [`approval-gated-tools.md`](approval-gated-tools.md) §6
  as approver-scope routing.

Tracked from [`_TODO.md`](_TODO.md) and [`_ROADMAP.md`](_ROADMAP.md) §C.2 / §B.2.
