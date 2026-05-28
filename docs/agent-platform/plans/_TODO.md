# Plans queue

Each bullet below is a feature we want to design and write its own plan file for.
Reminder list only — we discuss each one-by-one and produce a dedicated
`<feature>.md` next to this file. Move bullets off this list once their plan
exists.

For the consolidated, sequenced view of how these plans relate, see
[`_ROADMAP.md`](_ROADMAP.md).

- [x] ~~**Sandboxed agent inference for advanced capabilities**~~ — see
      [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md).
      Trust profiles (none → frozen → repo-readonly → repo-write → repo-pr),
      Modal-backed sandbox, code-execution tool family, artifact channel.

- [x] ~~**Self-healing agents**~~ — see
      [`self-healing-agents.md`](self-healing-agents.md).
      Read own history via LLM analytics (not `agent_session` JSONB),
      stratified sampling, replay + judge skill, always lands a draft.

- [x] ~~**Control flows / approval-gated tool use**~~ — see
      [`approval-gated-tools.md`](approval-gated-tools.md).
      Per-tool `requires_approval` on `AgentSpec`, runner intercept,
      `PendingApproval` table, UI + MCP approval surfaces.

- [x] ~~**Rate limiting of concurrent sessions**~~ — see
      [`rate-limiting-sessions.md`](rate-limiting-sessions.md).
      Per-agent caps in spec, per-team platform safety net, two-stage
      admission (ingress depth check + claim concurrent check),
      open-ask budget for approvals + elevation prompts.

- [x] ~~**Long-lived "waiting" sessions for explicit resume**~~ — see
      [`long-running-sessions.md`](long-running-sessions.md).

- [x] ~~**Per-session access elevation**~~ — see
      [`per-session-access-elevation.md`](per-session-access-elevation.md).
      Closes the Slack thread-reply security gap; session ACL model
      (specific principals + scope grants); elevation surfaces in Slack,
      chat UI, webhook; activity-log integration.

New bullets land here as freeform reminders; move them into their own plan
file (and out of this list) once the design lands.

- [x] ~~**Cron trigger scheduler**~~ — see
      [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md).
      Janitor runs `cronTick()` alongside its sweep; catch-up modes
      (`all` / `most_recent` / `skip`) bound the outage-recovery blast
      radius; `agent_cron_firing` table dedups across replicas; firings
      coalesce into long-running sessions via `external_key_reuse`.

- [x] ~~**Streaming deltas + unified reasoning knob**~~ — see
      [`streaming-and-reasoning.md`](streaming-and-reasoning.md).
      `PiClient.stream()` alongside `invoke()`; new event kinds for
      text/thinking/toolcall deltas; `spec.reasoning?: 'low' | 'medium'
    | 'high'` plumbed through `InvokeOpts`. Two features in one plan
      because they share the pi-ai stream surface.

- [x] ~~**Per-turn cost capture on the session row**~~ — see
      [`per-turn-cost-capture.md`](per-turn-cost-capture.md). New
      `usage_total` JSONB column on `agent_session`; runner accumulates
      tokens + cost on every `onTurnPersist`; backfill via a janitor
      endpoint. Replaces the derive-from-conversation summary helper
      for live reads, unblocks cost rollups + budget admission.

- [x] ~~**Typed config loader for env vars**~~ — see
      [`typed-config-loader.md`](typed-config-loader.md). One zod
      schema per service; `process.env.*` outside `config.ts` blocked
      by lint; generated deploy-runbook from the schemas. Pilots on
      agent-janitor first (smallest surface), sweeps to the rest.

- [x] ~~**Revision routing (subdomain + suffix)**~~ — see
      [`revision-routing.md`](revision-routing.md). Production:
      `<revision-prefix>.<slug>.agents.posthog.com/...`. Local dev:
      `/agents/<slug>-<revision-prefix>/...`. Both forms collapse into
      the same resolver path; existing `?revision_id=<uuid>` override
      stays as the canonical "I know the full UUID" form.

- [ ] **Auto-chaining via a gateway agent (Slack-first).** Today Slack
      mentions are routed 1:1 — `@my-helpdesk-agent` triggers
      `my-helpdesk-agent` and nothing else. Spec out a "gateway agent"
      pattern: a single `@posthog` (or similar) Slack-mentioned agent
      is the single entry point that routes the user's message to one
      of N downstream agents and forwards results back into the same
      Slack thread. Open design questions: (a) routing — does the
      gateway use an LLM classifier, declarative routes
      (`spec.routes[]`), or both? (b) chaining semantics — fire-and-
      forget vs await-and-relay vs streaming relay; (c) identity
      passthrough — the originating Slack user's principal must flow
      to the downstream session so the existing strict-principal +
      ACL machinery (per `per-session-access-elevation.md`) applies
      uniformly; the downstream `session.principal` should be the
      Slack user, not the gateway; (d) thread continuity — downstream
      replies thread under the same `slack:<channel>:<ts>`
      `external_key` so a single conversation appears unified;
      (e) generalization beyond Slack — the same pattern applies to
      webhook + chat-UI triggers (a single API endpoint dispatches
      across many agents). Composes with rate-limiting (a fan-out
      gateway burns capacity quickly), approval-gating (downstream
      tool calls retain their gates), and the cron trigger (a
      gateway agent _is_ the natural shape for an org-wide
      assistant). Promote to its own plan when picked up.
