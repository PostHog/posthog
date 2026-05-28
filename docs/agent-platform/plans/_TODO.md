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

- [x] ~~**Platform LLM analytics emission**~~ — see
      [`platform-llm-analytics.md`](platform-llm-analytics.md). Runner
      emits `$ai_generation` per pi-ai call + `$ai_span` per tool
      dispatch to a dedicated `agent_ai_events` Kafka topic. v0
      (emitter) shipped; v1 (forwarder consumer + free-flag billing
      logic) tracked in the plan §5. Marker:
      `$ai_origin: 'agent_platform_runner'` on every event.

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
      Initial pass landed; remaining gaps captured here.

      - [x] ~~janitor global express error handler~~ — shipped via
        `errorHandler(log)` in
        [`http-utils.ts`](../../../services/agent-janitor/src/http-utils.ts).
        Distinguishes `ZodError` (400 with structured issues) from
        unknown errors (500). All async routes wrapped in
        `asyncHandler` so rejections funnel through it.
      - [x] ~~zod-validate bodies + query at the edge~~ — every
        janitor endpoint now parses inputs via zod; the
        `typeof null === 'object'` hole on `PUT /revisions/:id/bundle`
        and the non-string content variant are covered by regression
        tests in
        [`server.test.ts`](../../../services/agent-janitor/src/server.test.ts).
      - [x] ~~process-level guards in all three services~~ —
        `installProcessHandlers(log)` in
        [`process-handlers.ts`](../../../services/agent-shared/src/runtime/process-handlers.ts);
        wired into the three `index.ts` files. `unhandledRejection`
        logs at error and continues; `uncaughtException` logs at
        fatal then exits (Node docs say continuing after this is
        unsafe).
      - [x] ~~typed config loader for envs~~ — shipped on the janitor
        in
        [`config.ts`](../../../services/agent-janitor/src/config.ts);
        closes the `parseInt('abc')` → `NaN` → `app.listen(NaN)`
        silent-bind footgun. Same pattern needs porting to runner +
        ingress (still touches `process.env` directly).
      - [x] ~~**bundle bulk-push has no per-file size cap**~~ —
        shipped 1MB-per-file + 4MB-per-bundle caps in
        [`server.ts`](../../../services/agent-janitor/src/server.ts)
        with zod `superRefine` issues pointing at the offending file.
      - [x] ~~**port the janitor `errorHandler` improvements back to
        ingress**~~ — shipped via
        [`http-utils.ts`](../../../services/agent-ingress/src/routing/http-utils.ts);
        every trigger route now wrapped in `asyncHandler`; ZodError /
        malformed JSON / AmbiguousRevisionError mapped to structured 400s.
      - [x] ~~**runner per-session error boundary**~~ — shipped: the
        whole pre-flight (revision load, secrets, sandbox acquire) now
        sits inside `runOne`'s try/catch so a malformed `spec` JSONB
        (ZodError out of `PgRevisionStore.rowToRev`) fails the one
        session instead of crashing the loop. Main loop's `claim()` is
        wrapped too — transient PG errors get logged and the loop
        keeps spinning.
      - [ ] **graceful-shutdown guarantees need explicit test
        coverage.** SIGTERM today flips the `shutdownController`,
        which propagates into pi-ai via the AbortSignal — the
        in-flight turn cancels, `runSession` returns
        `state: suspended`, the worker writes the session back as
        `queued`, and `loop()` only returns once every in-flight
        promise settles. There's no test that **proves** all of that
        end-to-end under realistic load (a fleet of sessions in
        different states — mid-turn, between turns, waiting on a
        tool, parked). Add cases covering:
        (a) shutdown mid-LLM-call — every in-flight session lands in
        `queued` (not `running`) with its conversation persisted, and
        no rows are lost / double-claimed by a sibling;
        (b) shutdown between turns — same invariant;
        (c) shutdown while a custom tool is executing — the sandbox
        is released, the session is requeued, the next worker can
        finish the tool call cleanly;
        (d) `loop()` doesn't return early — the promise it returns
        only resolves once every `inflight` entry has settled and
        written its state back to PG;
        (e) repeat-claim safety — a session left in `running` with
        a stale `claimed_at` is reaped by the sweep into `queued`,
        and the requeued instance behaves identically to a fresh one.
        **Deployment note:** k8s `terminationGracePeriodSeconds`
        must comfortably exceed the largest plausible LLM turn time
        + tool-call timeout (target an order of magnitude — minutes,
        not seconds). A too-short grace period turns SIGTERM into
        SIGKILL mid-turn; the safety net is the janitor's stuck-
        running sweep, but you don't want every rolling deploy to
        bounce sessions off that net.

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

- [x] ~~**Draft preview auth (via Django proxy)**~~ — see
      [`draft-preview-auth.md`](draft-preview-auth.md). Closes a
      confirmed gap where a draft with `auth.mode: 'public'` is
      invokable anonymously via the override paths regardless of the
      live revision's auth. Django proxies non-live invokes and
      attaches a signed `INTERNAL_SECRET`-style header; ingress
      refuses non-live invokes without it. Draft's own
      `spec.auth.mode` is unchanged — this is a layer above it.

- [x] ~~**Agent console website**~~ — see
      [`agent-console-website.md`](agent-console-website.md). A
      standalone read-mostly Next.js app under
      `services/agent-console/` styled with `@posthog/quill`. Logs
      in via PostHog OAuth, renders spec / bundle / revisions /
      sessions / logs against the existing REST API, and folds
      editing into a chat dock with a concierge agent (the
      `agent-authoring-flow` AI given a UI). The chat dock itself
      lives in a new sibling package `@posthog/agent-chat`
      (`packages/agent-chat/`) — the console embeds
      `<AgentChat />`, and the same component drops into a future
      `app.posthog.com` native dock or customer React SDK without a
      fork. Introduces a general **client-fulfilled tools**
      protocol on the runner: the spec declares `kind: "client"`
      tools (referencing well-known `@posthog/ui/*` contracts or
      bespoke ids), and a connecting client lists which ones it can
      fulfill via `client.handles[]`; the runner surfaces only the
      intersection to the model. First well-known tools are
      `@posthog/ui/focus` (navigate the read panel to whatever the
      agent is working on) and `@posthog/ui/toast`. User can toggle
      "Follow the agent" off without losing the agent's narration.
