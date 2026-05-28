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

- [`deploy-runbook.md`](docs/deploy-runbook.md) — env vars + smoke tests for the
  three node services (ingress, runner, janitor) and Django, the two-DB
  topology, what to set per environment.

_To add (post-cutover): an `architecture.md` that explains the running-system
shape (services, DBs, sandbox lifecycle); a `database-schema.md` with every
table + which DB owns it; the canonical `authoring-skill.md` once the templates
layer lands._

## plans/ (what we'd need to build)

- [`outstanding-work.md`](plans/outstanding-work.md) — the running TODO across the
  v2 packages. Authoritative index of in-flight / deferred items.
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
  old sessions. Keystone — the next several `_TODO.md` plans (rate limiting,
  approval gating, access elevation) all build on this lifecycle.
- [`skill-templates.md`](plans/skill-templates.md) — `SkillTemplate` +
  `CustomToolTemplate` library design (TODO C5).
- [`runtime-mcps.md`](plans/runtime-mcps.md) — `spec.mcps[]` runtime support
  for agents that consume third-party MCP servers (TODO C6).
- [`resumable-conversations.md`](plans/resumable-conversations.md) — design
  for loading prior session logs from ClickHouse on resume / display (TODO B8).
