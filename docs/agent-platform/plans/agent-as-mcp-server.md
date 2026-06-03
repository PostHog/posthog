# Design — agents expose their own MCP server

**Status:** v0 shipped (incl. v0.1 fix to scoping — see §3); v1 (`spec.mcp.tools[]`) pending. **Owner:** ben.

> **Runtime consumer side parked.** Agents exposing an MCP server still
> works (§9 of this plan). What's gone is the symmetric runtime path that
> let one agent declare _another_ agent's MCP in its own `spec.mcps[]`
> via `kind: 'agent'`. That runtime variant was ripped from
> [`runtime-mcps.md`](runtime-mcps.md) when an audit found no bundle
> consumed it — see that plan's "Post-ship simplification". Re-add this
> runtime path when a concrete agent-to-agent composability use case
> shows up; the server-side `/mcp` endpoint is still there waiting for it.

> Distinct from [`runtime-mcps.md`](runtime-mcps.md), which is about the
> runner _consuming_ third-party MCPs as tools. This plan is the inverse:
> the agent itself _exposes_ an MCP server that clients (Claude Code,
> Cursor, etc.) connect to.

## 1. Problem

After an authoring AI (or a human) builds and promotes an agent via the
existing authoring surfaces, there is no first-class way for the author —
or anyone else — to talk to the agent from their tool of choice:

- The Django `preview-proxy` covers draft iteration but is PostHog-internal:
  the connecting client has to know the proxy URL, mint a JWT through
  Django, and follow PostHog auth.
- The ingress `/agents/<slug>/run` endpoint accepts direct HTTP, but no
  major MCP client speaks raw chat HTTP.
- The Slack / webhook triggers work, but they presuppose Slack or a
  bespoke integration on the caller's side.

The clean story: the agent's MCP trigger should be a **first-class HTTP
MCP server**. An author registers the trigger in `spec.triggers`, the
ingress exposes a usable MCP endpoint at `/agents/<slug>/mcp`, and the
author copy-pastes the connect snippet into their tool of choice. No
Django proxy. No special tokens just for MCP. Whatever auth the agent
declares in `spec.auth` is the auth the MCP transport uses.

The `mcp` trigger already exists in the spec and the ingress has a
skeletal handler at
[`services/agent-ingress/src/triggers/mcp.ts`](../../../services/agent-ingress/src/triggers/mcp.ts).
What ships today is a hardcoded single `chat` tool with no auth gating —
enough to prove the wiring, not enough to be useful.

## 2. What a good agent MCP looks like

Three patterns for shaping the tool surface, ranked from least to most
opinionated:

### 2.1 Shape A — single `ask` tool (universal default)

One tool: `ask({ message, session_id? })`. The connecting client's LLM
sees one verb and routes to the agent based on the agent's
`description`. Continuation is via the optional `session_id`.

This is the **always-on default** for any agent with the MCP trigger
enabled. Zero design burden on the author. Works for any agent.

### 2.2 Shape B — author-curated workflow tools

`spec.mcp.tools[]` lets the author declare typed entry-points:

```yaml
mcp:
  tools:
    - name: request_refund
      description: Submit a refund request for a customer order.
      input_schema:
        type: object
        properties:
          order_id: { type: string, description: 'Order to refund' }
          reason: { type: string }
        required: [order_id, reason]
      prompt_template: |
        Process this refund request:
        Order: {{ order_id }}
        Reason: {{ reason }}
      external_key_template: 'refund:{{ order_id }}' # optional, dedups concurrent requests
```

Calling the tool renders the template, seeds a fresh session with that
as the first user message, returns `{ session_id, state }`.

Curated tools give the connecting LLM a typed, narrow API — better
routing, fewer wrong invocations. **The authoring AI populates these**
when building the agent (see §5). Hand-authoring works too.

### 2.3 Shape C — `ask` AND curated tools together

When curated tools exist, `ask` is **still exposed alongside them** as
the universal escape hatch. The connecting client can choose between
structured workflows and free-form chat based on whether the user's
intent maps to a curated tool.

## 3. Sessions as MCP resources

`tools/call` returns `{ session_id, state: 'queued' }` one-shot — no
inline blocking. To follow up, the client uses MCP **resources**:

- `agent://session/<id>` — read full session state (conversation,
  usage_total, status, principal).
- `resources/list` — recently-created sessions, scoped by the
  standard streamable-HTTP `Mcp-Session-Id` header (see below).

**Scoping model (post-v0.1 correction):**

- **`resources/read` — capability-by-URI on public agents.** Possession
  of `agent://session/<uuid>` is the gate; the UUID's 122 bits of
  entropy are the secret. This matches the standard MCP resources
  pattern (URI is the auth, same as a sharing link). For authenticated
  agents (`spec.auth.mode !== 'public'`), the strict-principal match
  applies on top — possession alone isn't enough.
- **`resources/list` — scoped by `Mcp-Session-Id` header.** The
  standard streamable-HTTP session id that every real MCP client
  (Claude Code, Cursor, the MCP Inspector) sends automatically after
  `initialize`. Sessions get tagged with the header at enqueue time
  via `external_key: 'mcp:<sessionId>:<uuid>'`; list filters on
  prefix match. Clients without the header see an empty list — they
  can still read sessions whose ids they hold, just not enumerate.
- **Earlier v0 used a non-standard `_meta.connectionId` echo** that
  no real client honoured. That mechanism is removed.

Live streaming via MCP `notifications/progress` is deferred — most
clients render them poorly today. Clients that want real-time updates
use the existing `/mcp/stream` SSE endpoint.

## 4. Auth — reuse `spec.auth`

The MCP transport applies the agent's `spec.auth.mode` exactly as the
chat / webhook triggers do:

- `mode: public` — anonymous MCP connections accepted.
- `mode: pat` — require PostHog PAT in `Authorization: Bearer phx_*`.
- `mode: shared_secret` — require the secret in `spec.auth.header`.
- `mode: posthog_internal` — server-to-server only, used by the
  authoring flow and the agent console.

This means a public agent gets a public MCP. A PAT-gated agent gets a
PAT-gated MCP. One auth model across every trigger; no new surface for
the author to think about.

## 5. The authoring AI angle — where the real leverage is

The authoring AI is the natural entity to design each agent's MCP
surface. When it builds an agent, it has the full picture: agent's
purpose, internal tools, intended users. It can deliberately shape the
external API to match.

Authoring AI workflow extension:

1. Author tells the authoring AI what they want.
2. It writes `agent.md`, picks tools, etc.
3. **It also writes `spec.mcp.tools[]`** — designed for the agent's
   specific purpose. A research agent gets `research({ topic })`. A
   support agent gets `handle_ticket({ content, severity })`. A
   compliance agent gets `audit_record({ record_id, period })`.
4. Promotes the revision.
5. Author runs `agent-applications-mcp-connect-info` to get the
   paste-ready snippet.

The authoring AI's prompt should include guidance on **what makes a
good MCP tool surface** — narrow verbs, typed inputs, descriptions
that tell a connecting LLM when to call this tool vs another. Same
principles we apply to the agent's own native-tool design.

## 6. Connect-info — `GET /agents/<slug>/mcp/connect-info`

**The ingress owns this**, not Django. The ingress is the source of
truth for routing mode, auth contract, and URL shape — Django would
just be shadowing that state via env vars. Putting connect-info on the
ingress also means anyone can `curl` it without going through PostHog
authoring auth: discovery is unconditionally public (the snippet itself
never carries real secrets, only placeholders, so there's no leak).

Returns:

```json
{
  "url": "https://my-helpdesk.agents.posthog.com/mcp",
  "transport": "http",
  "auth": { "mode": "pat", "header": "Authorization", "scheme": "Bearer" },
  "snippets": {
    "claude_code": {
      /* mcp.json fragment */
    },
    "cursor": {
      /* equivalent */
    },
    "generic_http": {
      /* type, url, headers */
    }
  }
}
```

The user pastes the appropriate snippet into their client's config.
For public agents the snippet has no auth header; for PAT-gated agents
the snippet has a placeholder the user fills in. No real secrets ever
flow through the snippet — Claude Code etc. resolve the placeholder
from their own secret stores.

When and where the URL is generated:

- **Path mode** (local dev): `http://localhost:3030/agents/<slug>/mcp`.
- **Domain mode** (prod): `https://<slug>.agents.posthog.com/mcp`.
- The ingress reconstructs the base URL from the inbound request
  (`req.protocol://req.get('host')`) by default; production sets
  `publicBaseUrl` explicitly via env when behind a proxy whose
  forwarded host doesn't match the public DNS.

## 7. Rollout

**v0 — default `ask` + auth + connect-info.** ✅ shipped.

- Rewrote the existing MCP trigger handler:
  - Renamed `chat` tool → `ask`, added optional `session_id` for
    continuation (→ `/send` instead of `/run`).
  - Wired `authorize()` against `spec.auth` on every JSON-RPC call;
    `initialize` is allowed pre-auth so a client can discover the
    protocol version before being asked to authenticate.
  - Added `resources/list` + `resources/read` for sessions; scope by
    MCP connection id minted on `initialize` and echoed back via
    `_meta.connectionId`.
- New `GET /agents/<slug>/mcp/connect-info` on the ingress (not
  Django — see §6). Public discovery endpoint returning URL, auth
  contract, and paste-ready snippets.
- Unit tests on the trigger for the new shape + an e2e case in
  `agent-tests/` pending.

**v1 — `spec.mcp.tools[]` author-curated.** After v0.

- Add `McpToolSchema` to the spec: `{ name, description, input_schema,
prompt_template, external_key_template? }`.
- `tools/list` returns `ask` AND the curated tools.
- `tools/call` for a curated tool renders the template + seeds a
  session.
- Template engine: minimal `{{ name }}` interpolation — no
  conditionals, no loops, no included files. Anything more expressive
  should be a real tool, not a template.
- Authoring AI prompt updated to populate `spec.mcp.tools[]` when
  building an agent.

**v2 — streaming via MCP notifications.** Deferred.

- Push `assistant_text` + `tool_call` events as
  `notifications/progress`. Behind a `spec.mcp.streaming: true` flag
  because client support is uneven.

**v3 — server-initiated tool registration.** Future.

- Agents that grow new capabilities can announce new MCP tools
  mid-connection via the standard MCP `tools/list_changed`
  notification. Lets a long-running session unlock new actions as
  state evolves.

## 8. Open questions

1. **Verb naming — `ask` vs `invoke` vs `run`?** Leaning `ask`
   because it parallels how humans talk about Slack-shaped agents. If
   the agent feels more like an action API (compliance audit, refund
   processing), `invoke` reads better. The author's MCP description
   should make this clear regardless of verb name — the connecting
   LLM reads descriptions, not verb names.
2. **Continuation in `ask` vs separate `continue` tool?** Going with
   `ask({ message, session_id? })`. One verb is easier to reason
   about. The optional `session_id` is the continuation signal.
3. **Connection scoping of resources.** v0 scopes session resources
   to the MCP connection that created them. A different design would
   let any connection see any session for an agent (if auth allows).
   The connection-scoped default is conservative; relaxing it later
   is additive.
4. **Schema validation of curated tool inputs.** v1 will validate
   `input_schema` against the call args at the MCP layer. If the
   validation fails, the connecting client gets a structured
   `tools/call` error and the session is never created.
5. **`resources/list` cardinality.** A long-lived MCP connection
   could accumulate hundreds of sessions. Cap the listing at the
   most recent N (default 50); older sessions are still readable
   via `resources/read` by URI if the client remembered the id.

## 9. Dependencies + what this enables

**Hard depends on:** nothing.

**Composes with:**

- [`per-session-access-elevation.md`](per-session-access-elevation.md) —
  same `SessionPrincipal` model. MCP sessions get a `principal: { kind:
'mcp', id: <connection-id> }` so the elevation / ACL machinery
  applies uniformly.
- [`draft-preview-auth.md`](draft-preview-auth.md) — for the case
  where someone wants to MCP-connect to a _draft_ revision (not
  live), the connect-info tool returns a URL pointing through the
  Django preview-proxy with the JWT mint flow. Live revisions use the
  direct ingress URL.
- [`agent-authoring-flow.md`](agent-authoring-flow.md) — the authoring
  AI is the right place to design the curated tool surface; this plan
  is the substrate that lets it pay off.

**What this unblocks:**

- The "build an agent → paste a command → use it from your IDE" loop
  Claude Code / Cursor users want.
- Agent-to-agent over MCP — agent A's `spec.mcps[]`
  ([`runtime-mcps.md`](runtime-mcps.md)) points at agent B's MCP
  endpoint. The two plans meet here.
