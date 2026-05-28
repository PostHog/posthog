# Roadmap — agent platform plans

Consolidated, sequenced view of every plan in this folder. The plans
themselves stay independent design docs; this file orders them and
surfaces the cross-cuts. When a plan lands as code, move it out of
`plans/` per the [README](../README.md), and update this roadmap to
strike it through.

For the raw queue of features still _waiting_ for a plan, see
[`_TODO.md`](_TODO.md). Every bullet there now has a corresponding
plan; this file is the order we'd build them in.

## Layers

We group the plans into four layers, roughly:

```text
┌─────────────────────────────────────────────────────────────┐
│  D. Authoring & self-improvement                            │
│     agent-authoring-flow.md · self-healing-agents.md        │
├─────────────────────────────────────────────────────────────┤
│  C. Capability extensions                                   │
│     sandboxed-agent-inference.md · runtime-mcps.md ·        │
│     skill-templates.md · resumable-conversations.md ·       │
│     cron-trigger-scheduler.md                               │
├─────────────────────────────────────────────────────────────┤
│  B. Trust & control                                         │
│     per-session-access-elevation.md ·                       │
│     approval-gated-tools.md · rate-limiting-sessions.md     │
├─────────────────────────────────────────────────────────────┤
│  A. Lifecycle foundation                                    │
│     long-running-sessions.md                                │
└─────────────────────────────────────────────────────────────┘
```

Higher layers depend on lower ones. We can build laterally within a
layer; we shouldn't reach down across layers without the foundation
in place.

## A. Lifecycle foundation

The keystone. Every plan above this depends on the state machine and
spec shape it introduces.

- [`long-running-sessions.md`](long-running-sessions.md) — extends
  the session state machine with a new `suspended` state, adds
  per-agent resumability config + context-compaction strategies
  (window / summarize / none), locks down the trigger-side contract
  for reopening old sessions. Status: design complete.

**What this layer must ship before anything above:**

- `suspended` state and `waiting → suspended → waiting` transitions.
- `spec.resume.*` validated at freeze time, backwards-compatible
  defaults.
- Janitor extension: `compactAged`, `wakeFromSuspended` policies.
- `external_key_reuse` policy on the trigger ingress.

## B. Trust & control

Three plans that, together, establish "who can do what" on a session.
Implementation order within this layer matters.

### B.1 [`per-session-access-elevation.md`](per-session-access-elevation.md)

**Sequence first.** This plan closes a **real security gap today**:
Slack thread replies bypass the strict-principal check that chat /
webhook triggers already enforce. v0 of this rollout ships the
symmetric `requireAclAccess(session, incoming)` extraction before
any UX work.

It also introduces the **activity-log integration** for the agent
platform — a shared dependency the next two plans rely on.

### B.2 [`approval-gated-tools.md`](approval-gated-tools.md)

Per-tool `requires_approval` flag on `AgentSpec`; runner intercepts
the call before dispatch; `PendingApproval` table; UI + MCP approval
surfaces. Composes with the elevation plan's principal model — the
`approvers: ["session_owner", "team_members"]` list resolves against
the same `SessionPrincipal` shape, and elevation grants automatically
widen who's eligible to approve when `approvers` includes scopes.

### B.3 [`rate-limiting-sessions.md`](rate-limiting-sessions.md)

Per-agent caps in spec; per-team platform safety net; two-stage
admission (ingress depth check + claim concurrent check); open-ask
budget that composes with **B.1** (elevation requests) and **B.2**
(pending approvals) to prevent notification flooding. Sequences last
in this layer because it observes/measures both of them.

**Shared cross-cut introduced by this layer:**

- _Activity-log integration._ Introduced by **B.1**; both **B.2**
  and **B.3** write to it. Implementation: one Django helper that
  the ingress / runner / janitor all call; wire once, reuse
  throughout.

## C. Capability extensions

Once trust + control exists, capability extensions become safe to
build on top.

### C.1 [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md)

Trust profiles (`none` → `frozen` → `repo-readonly` → `repo-write` →
`repo-pr`); promotes the existing `sandbox-modal.ts` stub to
first-class; whitelisted exec shell; pinned ref per session; artifact
channel for non-inline output. Hard-depends on **B.2** (every
`repo-pr` tool is mandatorily approval-gated) and **B.1** (high-trust
agents need strict principal enforcement).

### C.2 [`runtime-mcps.md`](runtime-mcps.md)

`spec.mcps[]` runtime support for agents that consume third-party
MCP servers (TODO C6). Independent of **C.1**; can ship in parallel.

### C.3 [`skill-templates.md`](skill-templates.md)

`SkillTemplate` + `CustomToolTemplate` library design (TODO C5).
Independent of **C.1** and **C.2**; can ship in parallel. Useful
input for the authoring layer.

### C.4 [`resumable-conversations.md`](resumable-conversations.md)

The read side of long-running sessions — loading prior session logs
from ClickHouse on resume / display (TODO B8). Depends on **A** for
the source-of-truth contract (conversation JSONB is canonical for
live state; ClickHouse is the audit log for display).

### C.5 [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md)

Wakes `cron`-trigger agents from the janitor. Small platform piece
sitting under C because it's a capability extension; depends on **A**
for the `external_key_reuse` policy that lets recurring firings
coalesce into one long-running session. Required for **D.2** v3.

**Shared cross-cut introduced by this layer:**

- _Artifact channel._ Introduced by **C.1** §7. Once a generalized
  "tool result is too big to inline → artifact handle" path exists,
  every other tool can return artifacts.

## D. Authoring & self-improvement

The top layer: agents that operate on agents.

### D.1 [`agent-authoring-flow.md`](agent-authoring-flow.md)

Speculative end-to-end design for an MCP-driven authoring AI:
discovery → spec → secrets punch-out → bundle authoring → test runs
with assertions → self-evaluation via a judge skill → preview link →
promote. Maps every step to what exists today vs what we'd need to
build, and embeds the reference authoring skill.

Foundational for **D.2** — the `agent_test_session` infrastructure +
judge skill defined here are reused verbatim.

### D.2 [`self-healing-agents.md`](self-healing-agents.md)

An agent that introspects its own historical sessions via LLM
analytics (`ai_events`, not `agent_session` JSONB), stratified-samples
real traffic, drafts a revision, runs it through the **D.1** test +
judge infrastructure, and lands a draft for human review.

**Shared cross-cut introduced by this layer:**

- _LLM analytics emission from the agent runner._ Introduced by
  **D.2** §3.1 but ships **regardless** of the rest of D.2 — unlocks
  PostHog's existing LLM analytics surface for agent users today.
  Tag every `$ai_generation` and `$ai_span` event with
  `$agent_application_id` + `$agent_revision_id`. This is the
  single biggest pre-D.2 piece of work.

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

## A walk-through of how to ship this

Assuming no parallelism, a reasonable order:

1. **A** — long-running sessions. Foundation. No prior dependencies.
2. **B.1** — elevation. Closes the Slack security gap (priority on
   its own merits). Introduces activity-log integration.
3. **B.2** — approval-gated tools. Builds on B.1's principal model.
4. **B.3** — rate limiting. Observability mode first; hard
   enforcement after.
5. **D.2 §11 v0** — wire LLM analytics emission from the runner.
   Unlocks observability for agents in production today, independent
   of the rest of self-healing.
6. **C.1** — sandboxed inference. `repo-readonly` first, then
   `repo-write`, then `repo-pr`. Each tier expands trust and depends
   on the prior layers' enforcement.
7. **C.2 / C.3 / C.4 / C.5** — runtime MCPs, skill templates,
   resumable conversations, cron scheduler. Independent; ship in
   parallel based on demand. **C.5** is a small janitor extension and
   is the cheapest of the four.
8. **D.1** — agent authoring flow. Test-run + judge infrastructure.
9. **D.2 §11 v1+** — the rest of self-healing. Manual introspection
   first, then replay-and-grade once D.1's test infrastructure
   exists, then cron-driven runs once **C.5** lands.

In practice we'll parallelize across layers, but the dependency arrows
remain: nothing in **B** ships without **A**; nothing in **C** /
**D** ships without **B**.

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
