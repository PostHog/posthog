# Design — in-band integration OAuth (`@posthog/integration-connect`)

**Status:** draft (v0.1). **Owner:** dmarticus.

> [`agent-concierge.md`](agent-concierge.md) names the concierge as the
> canonical agent-authoring surface. [`approval-gated-tools.md`](approval-gated-tools.md)
> introduces the "tool dispatches → session enters a structured waiting
> state → UI surfaces a card → user input resumes" pattern. This doc
> reuses that pattern for OAuth: the agent platform itself walks the
> user through connecting a third-party integration (Slack first,
> generic later), in-band, without leaving the dock.

## 1. Problem

Today an author can declare `integrations: ['slack']` in a spec, but
nothing in the authoring flow surfaces _whether_ Slack is actually
connected for the team. The current sequence to build a working
Slack-triggered agent:

1. Operator opens the agent console, asks the concierge to build a
   Slack-mention bot ("`make me @Jarvis that tells jokes`").
2. Concierge writes a spec with `triggers: [{type: 'slack', ...}]` +
   `integrations: ['slack']` + the right `@posthog/slack-*` tools.
3. Concierge freezes + promotes the bundle. Looks like success.
4. Operator triggers the bot from Slack. Session crashes — the runner
   calls `PgIntegrationStore.resolveForSpec(team_id, ['slack'])`, gets
   nothing, the Slack tool returns "integration not connected".
5. Operator goes hunting through PostHog UI for Settings → Integrations
   → Slack, walks Slack OAuth, comes back, retriggers. Works.

That's three layers of friction:

- **Discoverability.** The author surface has no signal that an
  integration is missing until runtime; the user finds out by their
  agent failing.
- **Context switch.** The user leaves the concierge dock, navigates
  PostHog UI, finds the Slack integration page, completes OAuth,
  returns. None of that is concierge-mediated; the concierge can't
  walk them through it or recover gracefully if they get lost.
- **Authoring AIs are blind.** When a remote authoring client (Claude
  Code via the concierge's MCP surface) writes a Slack bundle for a
  team it doesn't have UI access to, there is no way for it to say
  "actually, you need to connect Slack first — here's the link." It
  just produces a spec that crashes when invoked.

What we want: the concierge, mid-authoring, **calls a tool that
either confirms the integration is already connected or generates a
"click here to connect" affordance and waits for it to land**. The
session resumes when the user finishes the OAuth dance. The
concierge knows the resolved `integration_id` and bakes it into the
spec it freezes.

## 2. Today's primitives we build on

Almost all the pieces are already there:

| Piece                                                                                                                                                 | What it gives us                                                                                                                                                                                                                                                                                                                          |
| ----------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PostHog Settings → Integrations** ([`posthog_integration` table](../../../posthog/models/integration.py))                                           | The OAuth backend already exists. Slack, Salesforce, Hubspot, etc. share a single shape: `kind`, `integration_id`, `sensitive_config` (Fernet-encrypted access_token + refresh_token + metadata). The agent runner reads this same table via [`PgIntegrationStore`](../../../services/agent-shared/src/persistence/integration-store.ts). |
| **Approval-gated tool flow** ([`approval-gated-tools.md`](approval-gated-tools.md))                                                                   | Pattern: a tool returns a "queued + here's the link" synthetic result; an external action (approver decides; OAuth completes) re-injects a real `tool_result` later. The session stays alive — the model can talk to the user about other things while it waits.                                                                          |
| **`<AgentChat />` dock + structured cards** ([`ApprovalCard.tsx`](../../../packages/agent-chat/src/components/ApprovalCard.tsx))                      | The dock already renders inline approval cards via SSE-driven lifecycle events. Adding a sibling `IntegrationConnectCard` is a small frontend change.                                                                                                                                                                                     |
| **`integrationHostValidator` registry** ([`integration-host-registry.ts`](../../../services/agent-runner/src/resolvers/integration-host-registry.ts)) | Per-`kind` allowlist of OAuth host patterns. When this design lands, it's also where the OAuth start URL's host gets sanity-checked.                                                                                                                                                                                                      |
| **Spec-level `integrations: [...]`**                                                                                                                  | Already the declarative slot. After this design lands, freeze becomes the natural point to ensure each declared kind has a connected row before promoting.                                                                                                                                                                                |

What does **not** exist yet:

- A native tool that brokers OAuth between the agent and the Django
  OAuth backend.
- A "waiting on integration" lifecycle event / waiting reason.
- A cross-process resume signal — Django's existing OAuth callback
  doesn't know there's an agent session waiting on the result.
- A dock card for the connect affordance.

## 3. Proposed flow

End-to-end walkthrough for the Slack-bot case:

1. **User asks the concierge** to build a Slack bot.
2. Concierge drafts the spec. Before freeze it calls
   `@posthog/integration-connect({ kind: 'slack', scopes: ['chat:write', 'channels:history'] })`.
3. **Runner dispatches the tool.** The tool checks
   `PgIntegrationStore.list(team_id, 'slack')`:
   - **If a row exists** with the requested scopes (or a superset):
     return `{ integration_id, scopes_granted, status: 'already_connected' }`
     as a normal `tool_result`. Concierge takes the `integration_id` and
     bakes it into the spec (`team_integration_id` arg defaults). Done.
   - **If no row exists** (or scopes are insufficient): mint an OAuth
     start URL by calling Django (over the existing `INTERNAL_SECRET`
     channel — see [`janitor_client.py`](../../../products/agent_stack/backend/janitor_client.py)
     for the existing pattern, **NOT** the actual janitor client; the
     concierge would either reuse that auth channel or land a sibling
     Django endpoint specifically for OAuth-URL minting). Return a
     synthetic tool_result that says "I'm waiting on the user — they
     need to click `<oauth_url>` to connect Slack." Session enters
     `waiting_for_integration` lifecycle state with `{ kind, scopes, oauth_url }`.
4. **Dock renders an `IntegrationConnectCard`** keyed off the new
   lifecycle event. Same surface as `ApprovalCard.tsx`. Big "Connect
   Slack →" button, scope list, an "I already connected it elsewhere"
   refresh affordance.
5. **User clicks "Connect Slack"** → pops the standard PostHog Slack
   OAuth dialog (`SLACK_APP_CLIENT_ID` etc. from
   [`dynamic_settings.py:133-149`](../../../posthog/settings/dynamic_settings.py)).
   PostHog's existing callback handler verifies the OAuth state,
   writes the row to `posthog_integration`, then **publishes a
   `session_resume(session_id, kind, integration_id)` notification**
   on a Redis pubsub channel the runner is already consuming for
   `RedisSessionEventBus`.
6. **Runner consumes the resume**, looks up the freshly-written row,
   re-injects a real `tool_result` into the session with
   `{ integration_id, scopes_granted, status: 'connected' }`.
7. **Concierge continues**: bakes `integration_id` into the spec,
   freezes + promotes. The Slack bot can be triggered immediately.

Failure modes the design must handle:

- **User abandons the OAuth window.** Session sits in
  `waiting_for_integration` forever. Sweep timeout (see
  [`STUCK_WAITING_MS`](../../../services/agent-janitor/src/config.ts))
  already covers this — fall through to `failed` with reason
  `integration_connect_abandoned` after the existing 24h floor.
- **User connects via Settings → Integrations in another tab while
  waiting.** Dock card's "I already connected it" button re-runs the
  same tool, hits the "already_connected" branch, resumes the session
  with the same shape.
- **User grants a subset of scopes.** Tool returns `status: 'connected'`
  with `scopes_granted` reflecting what was actually granted; concierge
  is responsible for deciding whether that's enough. (Open question:
  should the platform refuse to resume if scopes are insufficient, or
  let the tool dispatcher catch it later at `@posthog/slack-post-message`
  call time? I'd lean letting the tool surface drive — the platform
  doesn't know which tools need which scopes; the model + the tool's
  declared `requires.scopes` do.)
- **Concierge dispatches `integration-connect` for a `kind` PostHog
  doesn't support.** Tool returns an error result with the supported
  set (`slack`, `salesforce`, `hubspot`, ...) so the concierge can fix
  the spec without a roundtrip through the user.

## 4. What we'd build

### 4.1 New native tool: `@posthog/integration-connect`

Lives next to `services/agent-tools/src/tools/slack.v1.ts`. Signature:

```ts
defineNativeTool({
  id: '@posthog/integration-connect',
  description:
    'Ensure a team-level integration of the given kind is connected, walking the user through OAuth if needed.',
  args: Type.Object({
    kind: Type.String(), // 'slack' | 'salesforce' | ...
    scopes: Type.Array(Type.String()), // requested OAuth scopes
    return_url_path: Type.Optional(Type.String()), // where to send the user after OAuth
  }),
  returns: Type.Union([
    Type.Object({
      status: Type.Literal('already_connected'),
      integration_id: Type.String(),
      scopes_granted: Type.Array(Type.String()),
    }),
    Type.Object({
      status: Type.Literal('connected'), // resume after OAuth round-trip
      integration_id: Type.String(),
      scopes_granted: Type.Array(Type.String()),
    }),
    Type.Object({
      status: Type.Literal('unsupported_kind'),
      supported_kinds: Type.Array(Type.String()),
    }),
  ]),
  requires: { integrations: [], scopes: [] }, // no integration is required to *call* this tool
  cost_hint: 'cheap',
  async run(args, ctx) {
    /* see §4.2-4.4 */
  },
})
```

The tool reads `ctx.integrations` to detect already-connected rows
(via the same store the runner threads in). When it needs OAuth, it
returns a special outcome that the dispatcher recognizes as "park
this session in `waiting_for_integration`."

### 4.2 New session lifecycle state + event

Schema addition to `services/agent-shared/src/spec/session-state.ts`
(or wherever `waiting_for_approval` lives — mirror that file). A new
waiting reason:

```ts
type WaitingReason =
    | { kind: 'waiting_for_approval'; ... }
    | { kind: 'waiting_for_integration'; integration_kind: string; scopes: string[]; oauth_url: string }
```

The SSE event the dock subscribes to grows by one variant. Both bus
impls (`MemorySessionEventBus`, `RedisSessionEventBus`) carry it
verbatim.

### 4.3 Django-side OAuth URL minting + callback hook

Two pieces:

**Mint endpoint.** A new internal Django endpoint
`POST /api/integrations/<kind>/oauth_url/` that takes `{ scopes,
team_id, session_id, return_url }` and returns `{ oauth_url, state }`.
Auth: `x-internal-secret` (`AGENT_JANITOR_SECRET` /
`INTERNAL_SECRET`) — same channel the janitor uses. Implementation:
generate the OAuth state, store the (state → session_id) mapping in
Redis with a short TTL, return the OAuth URL.

**Callback hook.** PostHog's existing Slack OAuth callback writes the
integration row and redirects the user. Extend it to:

1. Read the state, look up the originating `session_id`.
2. Publish `{ event: 'integration_connected', session_id,
integration_id, kind, scopes_granted }` on the same Redis channel
   the runner already consumes for lifecycle events.
3. Redirect the user back to the dock's `return_url` (the agent
   console, which auto-refreshes from SSE).

The Redis bridge is the only genuinely cross-process piece. Everything
else is one process reaching into existing infrastructure.

### 4.4 Runner-side resume

Worker subscribes to `integration_connected` events on the same Redis
channel that drives session events. When one arrives:

1. Find the session (must be in `waiting_for_integration` state,
   matching `session_id`, matching `kind`).
2. Pull the integration row via `PgIntegrationStore.get(...)` to
   capture `integration_id` + actual granted scopes.
3. Inject a synthetic `tool_result` with the `connected` shape into
   the session's pending tool-call.
4. Re-queue the session via the existing wake path
   (`approval-gated-tools.md` already pioneers this — reuse the same
   helper).

### 4.5 Dock surface

`packages/agent-chat/src/components/IntegrationConnectCard.tsx` —
sibling to `ApprovalCard.tsx`. Renders the OAuth URL as a primary
CTA, lists the requested scopes, has a secondary "Already connected
it elsewhere — check again" button that POSTs to a `/sessions/<id>/recheck_integration`
endpoint on the ingress (which calls the same `PgIntegrationStore.list`
and resumes if a row's appeared). Wires the same SSE feed.

## 5. Security model

The threat to address: **a malicious or buggy bundle author requests
OAuth for an unintended integration kind**, attempting to phish a
team owner into authorising a token the bundle then exfiltrates.

Defenses, layered:

- **Kind allowlist.** `@posthog/integration-connect` only handles
  kinds in a fixed registry (the same set Settings → Integrations
  supports). An unknown `kind` returns `status: 'unsupported_kind'`
  with the supported set; never mints a URL.
- **Scope minimization.** The OAuth URL only requests the scopes
  passed by the tool call. The concierge derives these from the spec's
  declared tools' `requires.scopes` set (already declared per-tool in
  e.g. [`slack.v1.ts:87`](../../../services/agent-tools/src/tools/slack.v1.ts)),
  so a bundle can't request scopes it doesn't have a tool for.
- **Team isolation.** The session's `team_id` is the only team that
  gets the integration row. The Redis resume signal verifies
  `integration.team_id === session.team_id` before resuming; a race
  where two teams complete OAuth simultaneously can't cross-resume.
- **OAuth consent screen as last resort.** The third-party (Slack)
  consent screen always shows the user what scopes are being granted.
  The user can deny. Same security floor as Settings → Integrations.
- **Existing `integrationHostValidator`** (now wired post the dev-escape
  PR) ensures the OAuth start URL is hosted on a domain the kind is
  bound to, so a bundle can't trick the dock into rendering a phishing
  link disguised as a "Connect Slack" button.

## 6. Phasing

**v0 — manual resume, Slack only.** Ship just enough for the
concierge-builds-jarvis story:

- `@posthog/integration-connect` handles only `kind: 'slack'`.
- No Redis bridge. The session enters `waiting_for_integration`, dock
  renders the card with a "Connect Slack →" button **and a "Check
  now" button**. User clicks Connect, completes OAuth in a separate
  tab, returns, clicks "Check now" — which calls a new ingress endpoint
  that triggers a re-dispatch of the tool. Tool sees the row, returns
  `already_connected`, session resumes.
- Lets us validate the dock UX, the spec shape, the
  `waiting_for_integration` state, and the security model without
  building the cross-process resume.

**v1 — automated resume via Redis bridge.** Add the Django OAuth
callback → Redis publish → runner consume chain. The "Check now"
button stays as a manual override but the default path is automatic.

**v2 — generic across all kinds.** Extend the kind allowlist to every
integration Settings → Integrations supports. Concierge skills get
templates per kind so it can author specs that connect Linear, Hubspot,
etc. on demand. Probably co-ships with a real catalogue endpoint that
exposes "what integrations does this PostHog instance support and what
scopes does each tool declare" so the concierge doesn't have to
hardcode per-kind knowledge.

## 7. Open questions

- **Scope insufficiency on grant.** If the user grants a subset of
  requested scopes, do we resume with a warning, or fail the tool
  call? My instinct: resume with `scopes_granted` reflecting reality
  and let the downstream tool (`@posthog/slack-post-message` etc.)
  surface the gap when it tries to call. The platform doesn't know
  which scopes are essential vs nice-to-have; the tool layer does.
- **Multi-workspace integrations.** Some teams connect two Slack
  workspaces. Today
  [`integration-store.ts:38-43`](../../../services/agent-shared/src/persistence/integration-store.ts)
  acknowledges this via `list(team_id, kind)` returning multiples. The
  tool should probably let the spec author opt into "the most recently
  connected one" vs "ask the user" via an explicit `pick: 'first' | 'last' | 'ask'`
  arg; default to `'first'`.
- **Token rotation.** What happens when a team's Slack token is
  invalidated (workspace owner kicks the PostHog app)? Today the
  symptom is a runtime 401 from `slack.com/api/...`. Should the tool
  catch that on a subsequent session, treat it as "needs reconnect,"
  and surface the same OAuth card? Probably yes, but it's a follow-up,
  not a v0 concern.
- **CI / scripted authoring.** If the concierge is being driven by
  Claude Code over MCP (not via the dock), the
  `waiting_for_integration` state has no UI to render the card.
  Probably the right thing is to return the synthetic `tool_result`
  with a status like `oauth_required` and the URL, so the authoring
  AI can paste it to the human running the CLI. The dock is one
  consumer of the waiting state, not the only one.

## 8. Non-goals

- **Building our own OAuth implementation.** Reuse Django's existing
  Slack OAuth flow verbatim. This design is about brokering, not
  re-implementing.
- **Token refresh.** Existing Integration model handles this. Out of
  scope.
- **Letting agents call integrations at runtime that the team hasn't
  authorized.** The tool establishes consent; it never bypasses it.
- **Replacing Settings → Integrations.** That surface still exists
  for "I want to manage my connections without going through an
  agent." This design is the agent-first onramp, not the only onramp.

## 9. Effort estimate

For v0 (manual resume, Slack only):

- New native tool + its test: ~half-day.
- `waiting_for_integration` lifecycle plumbing + dock card: ~half-day.
- Django mint endpoint + minor Slack callback edit: ~half-day.
- Ingress recheck endpoint: ~couple hours.
- Documentation + an `services/agent-tests/` case for the happy path:
  ~half-day.

Call it 2–3 days of focused work to get v0 demo-able.

v1 (Redis bridge) adds maybe a day on top — the runner already consumes
Redis pubsub for the event bus, so the wire-up is cheap; the discipline
is in nailing the resume race conditions (worker restart between
publish and consume → durable waiting state in PG, not just memory).

v2 (generic) is mostly a per-kind catalogue and concierge-skill effort,
not platform work. The platform changes from v1 should already
generalize.
