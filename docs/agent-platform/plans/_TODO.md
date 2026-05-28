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

All bullets have plans. New bullets land here as freeform reminders; move
them into their own plan file (and out of this list) once the design lands.
