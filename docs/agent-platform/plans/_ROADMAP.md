# Roadmap — agent platform plans

Consolidated, sequenced view of every plan in this folder. The plans
themselves stay independent design docs; this file orders them and
surfaces the cross-cuts. When a plan lands as code, annotate the entry
inline with the rollout phases that shipped (`v0 ✅` etc.) — full
strike-through is reserved for plans that landed in full and were
moved out of `plans/`.

For the raw queue of features still _waiting_ for a plan, see
[`_TODO.md`](_TODO.md). Every bullet there now has a corresponding
plan; this file is the order we'd build them in.

## Layers

We group the plans into five layers, roughly:

```text
┌─────────────────────────────────────────────────────────────┐
│  E. Human surfaces                                          │
│     agent-console-website.md                                │
├─────────────────────────────────────────────────────────────┤
│  D. Authoring & self-improvement                            │
│     agent-authoring-flow.md · self-healing-agents.md        │
├─────────────────────────────────────────────────────────────┤
│  C. Capability extensions                                   │
│     sandboxed-agent-inference.md · runtime-mcps.md ·        │
│     skill-templates.md · resumable-conversations.md ·       │
│     cron-trigger-scheduler.md · revision-routing.md ·       │
│     agent-as-mcp-server.md · streaming-and-reasoning.md     │
├─────────────────────────────────────────────────────────────┤
│  B. Trust & control                                         │
│     per-session-access-elevation.md ·                       │
│     approval-gated-tools.md · rate-limiting-sessions.md ·   │
│     per-turn-cost-capture.md · draft-preview-auth.md        │
├─────────────────────────────────────────────────────────────┤
│  A. Lifecycle foundation                                    │
│     long-running-sessions.md · typed-config-loader.md       │
└─────────────────────────────────────────────────────────────┘
```

Higher layers depend on lower ones. We can build laterally within a
layer; we shouldn't reach down across layers without the foundation
in place.

## Ownership

Staffed across three parallel workstreams for a team of 2 engineers +
1 UI loaner. The detailed sequencing/capacity view lives in the
team note; this is the at-a-glance map.

- **W1 — Lifecycle & Trust (Dylan):** the serial spine. B.1 security
  patch → A → B.1 → B.2 → B.3. One owner because it's all the same
  state-machine + spec surface.
- **W2 — Capabilities & Concierge (Danilo):** the spine-independent
  backend, parallel from day one. per-turn-cost → streaming → runtime-mcps → revision-routing / draft-preview-auth → cron (after A) → C.1 sandboxed (after B.2).
- **W3 — Human surfaces & Observability (Ben):** console + `@posthog/agent-chat`
  as the long pole, plus just-in-time UI tabs (elevation, approvals,
  proposals, session log, preview-URL) that land as each W1/W2 backend
  merges. `ai_events` emission. make UI useful and build an agent from the app.

Two cross-stream contracts to lock early: the **activity-log helper**
(W1 B.1, reused by B.2/B.3/C.1) and the **SSE delta shapes** (W2
streaming, consumed by the W3 chat package + session viewer).

Owner tags appear inline on each plan below as **Dylan** / **Danilo** /
**Ben**.

## A. Lifecycle foundation — **Dylan**

The keystone. Every plan above this depends on the state machine and
spec shape it introduces.

- [`long-running-sessions.md`](long-running-sessions.md) — adds an
  opt-in per-agent TTL on `completed` so a Slack assistant / weekly
  cron agent / multi-day incident thread can outlive the global 24h
  idle-close. **v0 is just the TTL knob**; the full `suspended` state +
  compaction pipeline is preserved in §3–§5 as future work for when
  usage data shows we actually hit the cost or context wall. Plan
  refreshed twice — once against the new state machine, once again
  after recognising compaction is a perf optimisation rather than a
  correctness requirement.
- [`typed-config-loader.md`](typed-config-loader.md) — one zod schema
  per service, lint-blocked `process.env.*` outside `config.ts`,
  generated runbook from the schemas. **v0 (janitor pilot) ✅ shipped;
  v1 (sweep to ingress + runner via `PlatformConfigSchema`) ✅
  shipped; v2 (generated runbook) + v3 (Django side) pending.**

**What this layer must ship before anything above (v0 slice):**

- `spec.resume.{enabled, max_completed_age_ms}` validated at freeze
  time, backwards-compatible defaults (`resume.enabled = false`
  preserves today's behaviour).
- Janitor sweep `idleCompletedClose` reads per-agent TTL when
  resume-enabled; falls back to global default otherwise.
- No new state, no new columns, no compaction, no runner rehydrate
  for v0. Those land later if real usage demands it.

- [`session-restart-and-state-machine.md`](session-restart-and-state-machine.md)
  — **Ben** — the load-bearing state machine
  `queued → running → completed → closed` (plus `cancelled`,
  `failed`) every trigger and resume path consumes. **v0 ✅ shipped:**
  state diagram codified, `meta-end-session` as the hard-close path,
  `allow_restart` on chat / MCP triggers reopens a closed session to a
  fresh user turn. Sits in §A because the rest of the platform builds
  on the contract.

## B. Trust & control — **Dylan**

Three plans that, together, establish "who can do what" on a session.
Implementation order within this layer matters.

### B.1 [`per-session-access-elevation.md`](per-session-access-elevation.md) — **Dylan** (UI panel **Ben**)

**Sequence first.** This plan closes a **real security gap today**:
Slack thread replies bypass the strict-principal check that chat /
webhook triggers already enforce. v0 of this rollout ships the
symmetric `requireAclAccess(session, incoming)` extraction before
any UX work.

It also introduces the **activity-log integration** for the agent
platform — a shared dependency the next two plans rely on.

**v0 (security patch + storage + check) ✅ shipped; v1 (Slack
elevation message + chat panel + per-session ACL scene + activity-log
helper) pending; v2 (delegation + org-admin override + MCP grant tool)
pending.**

### B.2 [`approval-gated-tools.md`](approval-gated-tools.md) — **v0 shipped**

Per-tool `requires_approval` flag on `AgentSpec`; runner intercepts
the call before dispatch; `agent_tool_approval_request` table with
canonical-args idempotency; janitor `/approvals/*` HTTP surface;
Django proxy via janitor_client (team-admin auth); non-blocking
session — model receives a synthetic queued tool_result and continues.
v1 adds the session-detail approvals tab + team-level inbox UI,
notification fan-out, and richer approver scopes (depends on B.1's
principal model).

**Cross-cut with C.2 — gating MCP tools is unresolved.** The v0
dispatcher only gates entries in `spec.tools`; MCP tools materialise
at runtime from `client.listTools()` and bypass the gate. The
concierge bundle's destructive tools (`*-destroy`,
`*-promote-create`, `set-env-create`) are the blocking customer.
Two designs (Option A: extend `McpRefExternal.tools[]`; Option C:
top-level `spec.approvals.rules[]`) — see C.2 entry above and
[`_TODO.md`](_TODO.md) "MCP tool approval gating" for the synthesis.
v1's richer approver scopes (`session_principal`) need to land
alongside whichever MCP-gating shape ships.

### B.3 [`rate-limiting-sessions.md`](rate-limiting-sessions.md) — **Dylan**

Per-agent caps in spec; per-team platform safety net; two-stage
admission (ingress depth check + claim concurrent check); open-ask
budget that composes with **B.1** (elevation requests) and **B.2**
(pending approvals) to prevent notification flooding. Sequences last
in this layer because it observes/measures both of them.

### B.4 [`per-turn-cost-capture.md`](per-turn-cost-capture.md)

`usage_total` JSONB on `agent_session`; runner accumulates tokens +
cost per turn via `accumulateUsage()`; janitor backfill endpoint.
Foundation for the cost-attribution surface and for
**B.3**-style budget admission. **v0 (column + accumulator) ✅
shipped; v1 (surface it via sessions-list + backfill endpoint) ✅
shipped; v2 (aggregates tool) pending.**

### B.5 [`draft-preview-auth.md`](draft-preview-auth.md)

Closes the gap where a draft with `auth.mode: 'public'` could be
invoked anonymously via the override paths regardless of the live
revision's auth. Django mints a short-lived HS256 JWT bound to
(app, rev) and proxies non-live invokes; ingress fail-closes on
missing / invalid token. **v1 (fail-closed enforcement) ✅ shipped;
v0 advisory mode skipped; v2 activity-log pending.**

### B.6 Per-session credentials + multi-mode auth — **Ben** — ✅ shipped

Per-session credential broker (`PgCredentialBroker`, encrypted column)
populated by ingress at /run + /send; multi-mode `spec.auth.modes[]`
schema accepting `public` / `pat` / `oauth` / `jwt` / `shared_secret`
/ `posthog_internal` in any combination on a single revision. The
credential broker is what lets PostHog-API native tools
(`@posthog/agent-applications-*`) execute against the asking user's
auth materials rather than a stored team-level token — resolved via
`ctx.credentials.resolve(target)` at dispatch time. **v0 (broker +
PG-backed encrypted column + multi-mode auth verifier + all native
tools routing through `credentials.resolve`) ✅ shipped via
`24e9577e17` (per-session credentials + encryption + auth modes) and
the `auth-modes.test.ts` e2e coverage.** No standalone plan file —
design lives in the `spec.auth` + credential-broker inline doc
comments. Worth a dedicated plan if a richer per-mode surface (OAuth
flows, JIT credential mint, token refresh) lands.

**Shared cross-cut introduced by this layer:**

- _Activity-log integration._ Introduced by **B.1**; both **B.2**
  and **B.3** write to it. Implementation: one Django helper that
  the ingress / runner / janitor all call; wire once, reuse
  throughout.

## C. Capability extensions

Once trust + control exists, capability extensions become safe to
build on top.

### C.1 [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md) — **Danilo** (after B.2)

Trust profiles (`none` → `frozen` → `repo-readonly` → `repo-write` →
`repo-pr`); promotes the existing `sandbox-modal.ts` stub to
first-class; whitelisted exec shell; pinned ref per session; artifact
channel for non-inline output. Hard-depends on **B.2** (every
`repo-pr` tool is mandatorily approval-gated) and **B.1** (high-trust
agents need strict principal enforcement).

### C.2 [`runtime-mcps.md`](runtime-mcps.md) — **Danilo**

`spec.mcps[]` runtime support for agents that consume third-party
MCP servers (TODO C6). Independent of **C.1**; can ship in parallel.
**✅ shipped** — flat `McpRefSchema` (`{ id, url, auth, secrets, tools }`),
MCP client wrapper, `buildAgentTools` integration, worker lifecycle,
e2e harness coverage, per-MCP-tool approval gating via `tools[]`
object form, prod-ready dispatcher + integration-host validator. The
old `kind: 'agent'` agent-to-agent variant was ripped out as orphan
code; re-adds when [`agent-as-mcp-server.md`](agent-as-mcp-server.md)
has a concrete consumer.

### C.3 [`skill-templates.md`](skill-templates.md) — **Danilo** (library UI **Ben**)

`SkillTemplate` + `CustomToolTemplate` library design (TODO C5).
Independent of **C.1** and **C.2**; can ship in parallel. Useful
input for the authoring layer. **v0 (registry backend models +
migrations + freeze-time resolution + `registry_api.py` viewset +
console `/registry` frontend with native / skills / tools detail
pages + concierge skill seeding) ✅ shipped — `e79a69e407` (registry
backend), `04f055e9ca` (platform tooling + generated artefacts),
`81728125ee` (concierge fixture + viewset wiring).** v1 (versioning
UX + cross-team sharing) pending.

### C.4 [`resumable-conversations.md`](resumable-conversations.md) — **Danilo** / next epoch (log rendering **Ben**)

The read side of long-running sessions — loading prior session logs
from ClickHouse on resume / display (TODO B8). Depends on **A** for
the source-of-truth contract (conversation JSONB is canonical for
live state; ClickHouse is the audit log for display).

### C.5 [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md) — **Danilo** (after A)

Wakes `cron`-trigger agents from the janitor. Small platform piece
sitting under C because it's a capability extension; depends on **A**
for the `external_key_reuse` policy that lets recurring firings
coalesce into one long-running session. Required for **D.2** v3.

### C.6 [`revision-routing.md`](revision-routing.md)

Two URL shapes for invoking a specific (non-live) revision:
`<rev-hex>.<slug>.agents.posthog.com` for prod, `/agents/<slug>-<rev-hex>/...`
for local dev. Collapses three legacy override forms
(`?revision_id=`, `x-agent-revision`, suffix) into one. **v0
(local-dev suffix) ✅ shipped; v1 (prod subdomain) partially shipped —
resolver in place, wildcard cert + UI affordance pending; v2
(activity log + observability) pending.**

### C.7 [`agent-as-mcp-server.md`](agent-as-mcp-server.md)

The mcp trigger on the ingress is a first-class HTTP MCP endpoint at
`/agents/<slug>/mcp`. **v0 (universal default `ask` + sessions-as-MCP-
resources + `spec.auth` reuse + public `/connect-info` discovery
endpoint) ✅ shipped; v1 (author-curated `spec.mcp.tools[]` typed
entry-points populated by the authoring AI) pending.** Lets a user
paste a connect command into Claude Code / Cursor and talk to the
agent directly. No Django proxy.

### C.8 [`streaming-and-reasoning.md`](streaming-and-reasoning.md)

`spec.reasoning` knob + `PiClient.stream()`. **v0a (reasoning
knob: spec field + InvokeOpts plumb-through) + v0b (`stream()` on
PiClient + FauxPiClient) + v1 (runner consumes stream, emits
delta events) ✅ shipped; v2 (opt-in delta filtering on /listen)
pending.**

### C.9 [`agent-memory.md`](agent-memory.md) — **Danilo** (Mnemion adapter **Danilo**)

Persistent KV store for agents — cross-session reads + writes keyed
by `(agent, scope, key)` with `agent` / `user:<id>` / `team` /
`session` scopes. Surfaced as a load-bearing gap in
[`_APP_IDEAS.md`](_APP_IDEAS.md) (10 of 13 candidate apps want it).
**v0 (`MemoryStore` interface + `S3MemoryStore` impl using markdown +
YAML frontmatter file format, MiniSearch BM25 backing the
`@posthog/memory-search` tool, six `@posthog/memory-*` native tools
wired through `ToolContext.memoryStore`) ✅ shipped via
`85c0bad0f3`.** Mnemion-adapted slice
([`agent-memory-mnemion-slice.md`](agent-memory-mnemion-slice.md))
covers the next round of write semantics + compaction; v1 picks up
from there.

### C.10 [`ai-gateway-integration.md`](ai-gateway-integration.md) — **Ben**

PostHog's ai-gateway as the billing source of truth for all
agent-platform LLM calls. Covers runner-side header injection
(`X-PostHog-Distinct-Id`, `X-PostHog-Trace-Id`, per-turn
`Idempotency-Key`), settled-cost fetch via `GET /v1/usage/<request_id>`
after every assistant turn, and the team `phc_` bearer plumbed
through the runner per-session. Companion plan
[`ai-gateway-introspection.md`](ai-gateway-introspection.md) covers
the read plane + console Billing tab. **v0 (local docker integration,
runner streams through gateway with cost merge, `llm-gateway →
ai-gateway` rename throughout) ✅ shipped via `6b3039cc8e` +
`d87155e2bd` + `19577c0cbc` + `1b9bcabd48` + `922f8e4417`; v1
(production wallet path, signed `$ai_origin` marker for platform-
internal exclusion) pending — couples with **D.2** §11 v1.**

### C.11 [`framework-system-prompt.md`](framework-system-prompt.md) — **Ben** — ✅ shipped

Framework-injected system-prompt preamble that lands ahead of the
author's `agent.md`: meta-tool decision rules, state contract, tool
failure handling, reasoning hint. Author opt-outs via
`spec.framework_prompt.omit[]` (typed escape hatch — see plan §7.4)
and version pinning via `framework_prompt.version_pin` for revision
reproducibility across platform upgrades. **v0 (preamble assembly +
sections catalogue + omit / version_pin validated at freeze time +
runner injects per-revision at session start) ✅ shipped. Preview
MCP tool that renders the assembled prompt for a given revision —
pending.**

**Shared cross-cut introduced by this layer:**

- _Artifact channel._ Introduced by **C.1** §7. Once a generalized
  "tool result is too big to inline → artifact handle" path exists,
  every other tool can return artifacts.

## D. Authoring & self-improvement — **Danilo**

The top layer: agents that operate on agents. Deferred to the next
planning cycle — except the `ai_events` emission carve-out below, which
**W2** ships now because it's independent and unlocks observability today.

### D.1 [`agent-authoring-flow.md`](agent-authoring-flow.md) — next epoch

Speculative end-to-end design for an MCP-driven authoring AI:
discovery → spec → secrets punch-out → bundle authoring → test runs
with assertions → self-evaluation via a judge skill → preview link →
promote. Maps every step to what exists today vs what we'd need to
build, and embeds the reference authoring skill.

Foundational for **D.2** — the `agent_test_session` infrastructure +
judge skill defined here are reused verbatim.

### D.2 [`self-healing-agents.md`](self-healing-agents.md) — §11 v0 **Danilo** now; rest next epoch

An agent that introspects its own historical sessions via LLM
analytics (`ai_events`, not `agent_session` JSONB), stratified-samples
real traffic, drafts a revision, runs it through the **D.1** test +
judge infrastructure, and lands a draft for human review.

### D.3 [`agent-concierge.md`](agent-concierge.md) — **Ben** (authoring AI **Ben**)

The agent-platform authoring AI. Sits at the seam between **D.1**
(authoring flow) and **E.1** (console): the concierge is the chat
dock's default agent and is itself authored as a deployed bundle in
`services/agent-tests/src/examples/agent-concierge/`. Its
forward-looking spec depends on **C.2** runtime-mcps PR 7 (per-MCP-
tool approval gating) + the `session_principal` approver scope from
**B.2** v1 — until those land, `scripts/seed.py` mechanically strips
`mcps[]` before push. **Status:** bundle authored, skills + client-
tool surface live; full deploy pending the C.2 + B.2 work tracked in
[`_TODO.md`](_TODO.md) "MCP tool approval gating."

**Shared cross-cut introduced by this layer:**

- _LLM analytics emission from the agent runner._ Introduced by
  **D.2** §3.1 but ships **regardless** of the rest of D.2 — unlocks
  PostHog's existing LLM analytics surface for agent users today.
  Tag every `$ai_generation` and `$ai_span` event with
  `$agent_application_id` + `$agent_revision_id`. This is the
  single biggest pre-D.2 piece of work. **Promoted to its own plan
  ([`platform-llm-analytics.md`](platform-llm-analytics.md)); v0
  (runner captures via standard PostHog ingestion / posthog-node) ✅
  shipped; v1 (signed `$ai_origin` marker for billing exclusion of
  platform-internal runs) pending.**

## E. Human surfaces — **Ben**

The console. Read-mostly UI for the broader human audience —
reviewers, operators, and authors who don't drive the MCP directly.
Sits on top because it consumes everything below: the lifecycle and
spec shape from **A**, the principal model from **B.1**, the SSE
stream from **C.streaming**, the preview URLs from **C.routing**,
the draft-auth gate from **B.draft-preview**, and the authoring
flow from **D.1**.

### E.1 [`agent-console-website.md`](agent-console-website.md)

Standalone Next.js app at `services/agent-console/`, styled with
[`@posthog/quill`](../../../packages/quill), logging in via PostHog
OAuth (through the existing `oauth-proxy`). Every read surface maps
to an existing REST endpoint; every write happens through a
**concierge agent** session — the **D.1** authoring AI given a chat
dock — whose principal is the human user (so mutations log against
the user, not a PostHog org).

The chat dock itself ships as a new sibling package
`@posthog/agent-chat` (at `packages/agent-chat/`, sibling to
`packages/quill/`). The console embeds `<AgentChat />`; the same
component drops into a future `app.posthog.com` native dock or
customer React SDK without a fork.

Introduces one new platform-level primitive:

- **Client-fulfilled tools.** The spec declares `kind: "client"`
  tools alongside its native and custom tools — either referencing
  a well-known contract (`from_native: "@posthog/ui/focus"`) or
  defining a bespoke one inline. A connecting client lists which
  ones it can handle via `client.handles[]` at session open. The
  runner surfaces only the intersection to the model; calls flow as
  `client_tool_call` SSE events to the originating client and
  results post back via a new ingress endpoint. Bounded payloads,
  per-call timeout, no ability for the client to extend the model's
  tool surface beyond what the spec author approved. Flagship
  well-known tools: `@posthog/ui/focus` (navigate the read panel to
  whatever the agent is working on) and `@posthog/ui/toast`. The
  protocol generalizes to any chat-trigger client — Slack message
  viewers, MCP hosts, embedded SDK widgets — and is the natural
  extension point for future UX affordances.

**Shared cross-cut introduced by this layer:**

- _Client-fulfilled tool protocol._ Introduced by **E.1** §8 but
  generalizes beyond the console. Any future client-side chat
  surface declares `client.handles[]` for the well-known
  `@posthog/ui/*` set it supports; spec authors don't re-author
  per client kind.

## Cross-cut: shared infrastructure pieces

Three pieces of infrastructure get introduced once and reused
everywhere. Worth calling out so the team doesn't accidentally build
each one three times.

| Piece                        | First introduced in                 | Reused by                                                                  |
| ---------------------------- | ----------------------------------- | -------------------------------------------------------------------------- |
| Activity-log integration     | B.1 per-session-access-elevation §8 | B.2 approval-gated-tools §6, B.3 rate-limiting §9, C.1 sandboxed §9        |
| Artifact channel             | C.1 sandboxed-agent-inference §7    | B.2 approval-gated approver-edit UX, C.4 resumable-conversations rendering |
| ai_events trace emission     | D.2 self-healing-agents §3.1        | D.1 authoring flow (test results), all observability surfaces              |
| `agent_test_session` + judge | D.1 agent-authoring-flow §test-runs | D.2 self-healing-agents §5 replay-and-grade                                |
| Client-tool protocol         | E.1 agent-console-website §8        | Any future chat-trigger client surface (Slack viewers, MCP hosts, SDKs)    |
| Approval gating surface ⚠️   | B.2 approval-gated-tools §3 (v0)    | C.2 runtime-mcps (unresolved — see \_TODO.md "MCP tool approval gating")   |

## A walk-through of how to ship this

Assuming no parallelism, a reasonable order:

1. **A** — long-running sessions. Foundation. No prior dependencies.
   _typed-config-loader v0+v1 ✅ already shipped (the only **A**-layer
   piece in code so far)._
2. **B.1** — elevation. Closes the Slack security gap (priority on
   its own merits). Introduces activity-log integration.
3. **B.2** — approval-gated tools. Builds on B.1's principal model.
4. **B.3** — rate limiting. Observability mode first; hard
   enforcement after.
   _B.4 per-turn-cost-capture v0+v1 ✅ shipped early — orthogonal
   to B.1–B.3, lands the column B.3 budget admission will need.
   B.5 draft-preview-auth ✅ shipped early — closes the draft-invoke
   gap independent of the strict-principal extraction._
5. **D.2 §11 v0** — wire LLM analytics emission from the runner.
   _Promoted to its own plan
   ([`platform-llm-analytics.md`](platform-llm-analytics.md)); v0
   runner-side capture ✅ shipped — next ask is the v1 signed-origin
   marker + billing-side verifier._
6. **C.1** — sandboxed inference. `repo-readonly` first, then
   `repo-write`, then `repo-pr`. Each tier expands trust and depends
   on the prior layers' enforcement.
7. **C.2 / C.3 / C.4 / C.5** — runtime MCPs, skill templates,
   resumable conversations, cron scheduler. Independent; ship in
   parallel based on demand. **C.5** is a small janitor extension and
   is the cheapest of the four.
   _C.6 revision-routing v0 ✅ shipped (local-dev suffix), v1
   partially shipped; C.7 streaming-and-reasoning v0a ✅ shipped
   (reasoning knob), stream surface pending._
8. **D.1** — agent authoring flow. Test-run + judge infrastructure.
9. **D.2 §11 v1+** — the rest of self-healing. Manual introspection
   first, then replay-and-grade once D.1's test infrastructure
   exists, then cron-driven runs once **C.5** lands.
10. **E.1** — agent console website. Read-mostly v0 (overview,
    bundle, revisions, sessions) ships on top of **A** + **C.streaming**
    - **C.routing** alone — does not strictly require **D.1** to land
      first because the chat dock can drive any agent (the concierge
      itself can ship as a hand-authored bundle until the templates
      layer arrives). The client-tool protocol is a runner change but
      its surface is opt-in, so it's safe to ship behind a flag while
      the console iterates.

In practice we'll parallelize across layers, but the dependency arrows
remain: nothing in **B** ships without **A**; nothing in **C** /
**D** ships without **B**; nothing in **E** ships without the
streaming + principal pieces it consumes.

## What's _not_ in scope here

The TODO bullets are now all designed. Bullets that haven't been
raised yet, but we know exist as gaps in the plans above:

- **GitHub App scoping for `repo-pr` agents.** **C.1** §11 v2 calls
  it out. Future plan.
- **Multi-agent shared-identity ("@incident-bot" org-wide agents).**
  Hinted in **B.1** §11. Future plan.
- **Cost-attribution / budgets surface.** Hinted across **B.3**,
  **C.1**, **D.2**. Future plan.
- **Agent fleet view / cross-agent observability dashboard.** Hinted
  in **B.3** §12 and **D.2** §3.2. Future plan once the aggregated
  views exist.

Add new gaps to [`_TODO.md`](_TODO.md) as freeform bullets; promote
to their own plan + this roadmap when designed.
