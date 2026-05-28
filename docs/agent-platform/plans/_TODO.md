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

- [ ] **MCP tools for invoking a created agent.** The `agent_stack`
      MCP surface today is authoring-only (`agent-applications-*`,
      `agent-applications-revisions-*`). After an authoring harness
      (Claude Code, etc.) creates and promotes an agent via MCP, it
      has no in-band way to talk to it — the ingress runtime endpoints
      (`/agents/<slug>/run`, `/send`, `/listen`) aren't wrapped as
      tools, so the next step isn't discoverable from the tool list.
      Add `agent-invoke` / `agent-send` / `agent-listen` (SSE stream
      shape TBD for MCP) so the authoring AI can iterate end-to-end
      without leaving MCP. See [`agent-authoring-flow.md`](agent-authoring-flow.md)
      for the broader test-run surface this slots into.

- [ ] **Defensive programming across the three node services.** A
      malformed request to the janitor today can take the process down.
      Initial pass landed; remaining gaps captured here. - [x] ~~janitor global express error handler~~ — shipped at
      [`server.ts:438`](../../../services/agent-janitor/src/server.ts)
      via `errorHandler(log)` in
      [`http-utils.ts`](../../../services/agent-janitor/src/http-utils.ts).
      Distinguishes `ZodError` (400 with structured issues) from
      unknown errors (500). All async routes wrapped in
      `asyncHandler` so rejections funnel through it. - [x] ~~zod-validate bodies + query at the edge~~ — every
      janitor endpoint now parses inputs via zod; the
      `typeof null === 'object'` hole on `PUT /revisions/:id/bundle`
      and the non-string content variant are covered by regression
      tests in
      [`server.test.ts`](../../../services/agent-janitor/src/server.test.ts). - [x] ~~process-level guards in all three services~~ —
      `installProcessHandlers(log)` in
      [`process-handlers.ts`](../../../services/agent-shared/src/runtime/process-handlers.ts);
      wired into the three `index.ts` files.
      `unhandledRejection` logs at error and continues;
      `uncaughtException` logs at fatal then exits (Node docs say
      continuing after this is unsafe). - [ ] **`parseInt(process.env.PORT ?? '8082', 10)` yields `NaN`** if
      `PORT="abc"`, and `app.listen(NaN)` silently binds a random
      port. Same pattern for `STUCK_RUNNING_MS`, `STUCK_WAITING_MS`,
      `MAX_RETRIES`, `SWEEP_INTERVAL_MS`, `AGENT_MAX_CONCURRENCY`.
      Validate envs at boot (fail loud) — ties into the
      “clean up all env vars” bullet above; a typed config loader
      is the natural home. - [ ] **bundle bulk-push has no per-file size cap** beyond the 8MB
      JSON limit; a single 7MB file path slips through and lands on
      disk. Add a per-path and per-bundle ceiling on the
      `PUT /revisions/:id/bundle` and `PUT /revisions/:id/file`
      endpoints. - [ ] **port the janitor `errorHandler` improvements back to
      ingress.** Ingress has a global error handler at
      [`routing/server.ts:66`](../../../services/agent-ingress/src/routing/server.ts)
      but doesn't distinguish `ZodError` and doesn't wrap async
      routes in `asyncHandler`. Same hardening pattern applies.
      Ingress validates webhook / chat / slack bodies inside
      per-router code; some paths are already covered, but the
      consistent shape would be a wrapper + a single error
      middleware. - [ ] **runner has no equivalent.** The runner has no HTTP
      surface, but the worker loop has try/catch around individual
      sessions. Audit: does a malformed `conversation` JSONB or a
      broken `spec` blob in PG crash the loop, or just fail the one
      session? If the former, add a per-session error boundary.

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
