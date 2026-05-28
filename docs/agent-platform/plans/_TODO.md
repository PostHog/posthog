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

- [ ] **Streaming deltas into SessionEventBus.** Today `run-turn.ts`
      calls `pi.invoke()` and waits for the full `AssistantMessage`,
      then emits one `assistant_text` event per text block. Swap to
      `stream()` and forward `text_delta` / `thinking_delta` /
      `toolcall_delta` events into `bus.publish` so `/listen` SSE
      consumers see tokens live. Tool dispatch still waits for
      `toolcall_end` (full args). Add `assistant_text_delta` +
      `assistant_thinking` event kinds; `PiClient` grows a `stream()`
      method alongside `invoke()`.

- [ ] **Per-turn cost capture on the session row.** pi-ai populates
      `result.usage.cost.{input,output,total}` and the runner currently
      drops it — only `tokensIn`/`tokensOut` get logged. Accumulate
      per-turn tokens + cost onto the session row (new `usage_total`
      jsonb column on `agent_session_v2`, persist via `onTurnPersist`).
      Foundation for cost-attribution / budgets surface (a future plan
      hinted at across rate-limiting / sandboxed / self-healing).

- [ ] **Unified `reasoning` knob on `AgentSpec`.** Reasoning models
      (Anthropic extended thinking, OpenAI o-series, Gemini thinking)
      get only provider defaults today. Add optional
      `spec.reasoning?: 'low' | 'medium' | 'high'`; runner forwards it
      to pi-ai via `completeSimple()` / `SimpleStreamOptions.reasoning`.
      One config, all providers.

- [ ] Clean up all env vars django or nodejs side
      Some env vars do direct process.env access - this should all be abstracted to a typed config loader or the standard django settings concept with sensible defaults

- [ ] **Slug-with-revision-suffix triggers for non-live revisions.**
      Today draft / ready revisions are reachable via
      `?revision_id=<full-uuid>` (or `x-agent-revision` header). Add an
      ergonomic slug-form alternative — e.g. `/agents/my-app-ABC123/...`
      where `ABC123` is the leading hex of a revision id under the
      `my-app` application. Resolver tries the suffix split first; on
      ambiguous prefixes it 400s rather than picking. Pairs naturally
      with the existing `?revision_id` override (uuid wins, suffix is
      shorthand). Useful for Slack mentions / webhook URLs where you
      want to share a draft link without exposing the full UUID.
