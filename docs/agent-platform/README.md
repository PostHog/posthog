# Agent platform docs

This tree splits **what exists** from **what's planned**:

```text
docs/agent-platform/
├── docs/    — implemented; references for operating + extending the platform today
└── plans/   — designs / open questions; nothing has been built yet, or only partially
```

Move a file from `plans/` to `docs/` when the design lands as code (and prune
the "open questions" section once they're answered by the implementation).

## docs/ (what exists)

- [`local-dev.md`](docs/local-dev.md) — bringing the stack up locally, the
  three paths to drive it (`bin/run-agent`, `bin/seed-agent-session`, local
  MCP), the e2e test harness in `services/agent-tests`, the
  vital-feature-needs-a-case rule, debugging recipes.
- [`deploy-runbook.md`](docs/deploy-runbook.md) — env vars + smoke tests for the
  three node services (ingress, runner, janitor) and Django, the two-DB
  topology, what to set per environment.

_To add (post-cutover): an `architecture.md` that explains the running-system
shape (services, DBs, sandbox lifecycle); a `database-schema.md` with every
table + which DB owns it; the canonical `authoring-skill.md` once the templates
layer lands._

## plans/ (what we'd need to build)

Start with [`_ROADMAP.md`](plans/_ROADMAP.md) for the sequenced view across
all plans and the shared cross-cuts between them. [`_TODO.md`](plans/_TODO.md)
is the queue of features waiting for a plan.

- [`agent-authoring-flow.md`](plans/agent-authoring-flow.md) — speculative
  end-to-end design for an MCP-driven authoring AI: discovery → spec → secrets
  punch-out → bundle authoring → test runs with assertions → self-evaluation
  via a judge skill → preview link → promote. Maps every step to what exists
  today vs what we'd need to build, and embeds the **reference authoring
  skill** an authoring AI would load to learn the platform.
- [`long-running-sessions.md`](plans/long-running-sessions.md) — Phase A
  foundation: extends the session state machine with a new `suspended` state,
  adds per-agent resumability config + context-compaction strategies (window /
  summarize / none), and locks down the trigger-side contract for reopening
  old sessions. Keystone — every plan below builds on this lifecycle.
- [`per-session-access-elevation.md`](plans/per-session-access-elevation.md) —
  session ACL model + elevation surfaces (Slack blocks, chat-UI panel,
  webhook URL); closes a real security gap where Slack thread replies bypass
  strict-principal enforcement; introduces activity-log integration that the
  next two plans reuse.
- [`approval-gated-tools.md`](plans/approval-gated-tools.md) — per-tool
  `requires_approval` flag on `AgentSpec`, runner intercept, `PendingApproval`
  table, UI + MCP approval surfaces. Builds on long-running-sessions.
- [`rate-limiting-sessions.md`](plans/rate-limiting-sessions.md) — per-agent
  caps in spec, per-team platform safety net, two-stage admission (ingress
  depth check + claim concurrent check), open-ask budget composing with
  approvals + elevation.
- [`sandboxed-agent-inference.md`](plans/sandboxed-agent-inference.md) — trust
  profiles (none → frozen → repo-readonly → repo-write → repo-pr) mapping to
  the existing `SandboxImpl` interface; promotes the Modal sandbox stub to
  first-class; whitelisted exec shell; pinned ref per session; artifact
  channel for non-inline output.
- [`self-healing-agents.md`](plans/self-healing-agents.md) — an agent that
  introspects its own historical sessions via LLM analytics, stratified-samples
  real traffic, drafts a revision, replays it through a judge skill, and lands
  the draft for human review.
- [`skill-templates.md`](plans/skill-templates.md) — `SkillTemplate` +
  `CustomToolTemplate` library design (TODO C5).
- [`runtime-mcps.md`](plans/runtime-mcps.md) — `spec.mcps[]` runtime support
  for agents that consume third-party MCP servers (TODO C6).
- [`resumable-conversations.md`](plans/resumable-conversations.md) — design
  for loading prior session logs from ClickHouse on resume / display (TODO B8).
- [`agent-memory.md`](plans/agent-memory.md) — persistent cross-session
  store keyed by `(agent, scope, key)` with `agent` / `user:<id>` /
  `team` / `session` scopes. Surfaced by [`_APP_IDEAS.md`](plans/_APP_IDEAS.md)
  as the single highest-leverage gap (10 of 13 candidate apps want
  it). Plan is in options-mode — 12 design dimensions each present a
  menu; pick per dimension before implementing.
- [`agent-console-website.md`](plans/agent-console-website.md) — standalone
  Next.js app under `services/agent-console/`, styled with `@posthog/quill`,
  logging in via PostHog OAuth. Read-mostly UI over the existing REST API
  (spec, bundle, revisions, sessions, logs); editing happens through a chat
  dock with a concierge agent (the authoring AI given a UI). The chat dock
  itself lives in a new sibling package `@posthog/agent-chat` so it can
  later be embedded in `app.posthog.com` or a customer React SDK without a
  fork. Introduces a general **client-fulfilled tools** protocol on the
  runner: the spec declares `kind: "client"` tools, the client opts in to
  the subset it can handle, the runner surfaces only the intersection to
  the model. Flagship well-known tool is `@posthog/ui/focus`, which
  navigates the read panel to whatever the agent is currently working on.
