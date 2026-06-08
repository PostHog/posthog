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

- [ ] **Tailscale-backed MCP integration** — **PARKED** (see
      [`tailscale-mcps.md`](tailscale-mcps.md) §"Why this is parked").
      The design holds, but the Node ↔ Tailscale integration story is
      rougher than expected: `tsnet` is Go-only, no first-party Node
      SDK exists, and the cross-language `tailscaled` daemon path only
      supports one tailnet per process — which is the constraint that
      makes the multi-customer story require a custom Go binary in the
      agent-runner pod. Not worth picking up without a concrete customer
      ask, official Tailscale Node bindings landing, or a second PostHog
      product needing the same "PostHog Cloud reaches into customer's
      private network" plumbing.

- [ ] **Cron trigger scheduler** (Dylan — picking up after runtime-mcps
      PR 7) — see
      [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md).
      Janitor runs `cronTick()` alongside its sweep; catch-up modes
      (`all` / `most_recent` / `skip`) bound the outage-recovery blast
      radius; `agent_cron_firing` table dedups across replicas; firings
      coalesce into long-running sessions via `external_key_reuse`.
      Plan was checked off prematurely — the most recent commit on the
      plan file is `078ce5bb89 wip — cron plan, auth refresh, hogli
    ai-gateway slot`; no `cronTick` or `agent_cron_firing` exist in
      the codebase yet.

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
      captures `$ai_generation` per pi-ai call + `$ai_span` per tool
      dispatch through standard PostHog ingestion (posthog-node
      `/capture`). v0 shipped; v1 (signed `$ai_origin` marker for
      billing-side exclusion of platform-internal runs) tracked in
      the plan §5. Every event carries the unsigned placeholder
      `$ai_origin: 'agent_platform_runner'` so the property slot
      exists from day one.

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

- [x] ~~**Agents expose their own MCP server**~~ — see
      [`agent-as-mcp-server.md`](agent-as-mcp-server.md). The mcp
      trigger on the ingress is now a first-class HTTP MCP endpoint
      at `/agents/<slug>/mcp` with a universal default `ask({
message, session_id? })` tool, sessions exposed as MCP
      resources (`agent://session/<id>`) scoped by per-connection
      id, and `spec.auth` reused as the transport auth. Discovery
      lives on the ingress at `GET /agents/<slug>/mcp/connect-info`
      — public endpoint, returns the URL + auth contract + paste-ready
      snippets for Claude Code / Cursor / generic mcp.json. v1
      (`spec.mcp.tools[]` author-curated entry-points) pending.

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

- [x] ~~**Framework system prompt — flesh out the content**~~ — see
      [`framework-system-prompt.md`](framework-system-prompt.md). Meta-tool
      decision rules, conversation-state contract, tool failure handling,
      reasoning-budget hint, author-prompt vs framework-prompt seam,
      override markers, and an MCP tool to preview the assembled prompt.

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

- [ ] **Bundle manifest schema** — **superseded** by
      [`typed-bundle-authoring-api.md`](typed-bundle-authoring-api.md).
      Original idea (spec-derived path allowlist on a generic file
      API) is moot when the file API itself goes away — see
      [`bundle-manifest-schema.md`](bundle-manifest-schema.md) for
      the archived design. Keep the bullet here as a back-reference
      until the typed API ships and we archive both entries
      together.

- [ ] **Typed bundle authoring API + full janitor e2e suite** — see
      [`typed-bundle-authoring-api.md`](typed-bundle-authoring-api.md).
      Replace the generic `/file?path=X` bundle store with typed
      resource endpoints (`/agent_md`, `/skills/:id`, `/tools/:id`,
      `/bundle` for GET+PUT). `spec.skills[]` / `spec.tools[]`
      become server-derived at freeze — orphans and spec/bundle drift
      become structurally impossible. Tool upload runs a static-AST
      shape check (TypeScript compiler API, no `vm.runInContext`) +
      esbuild compile in one pass; failures return 422 at upload, not
      at session-start. Django collapses to a thin proxy; the janitor
      HTTP contract is the source of truth, pinned by a comprehensive
      e2e suite at `services/agent-tests/src/cases/typed-bundle-authoring.test.ts`
      (round-trip, per-resource semantics, delete, full-replace,
      shape pipeline, spec derivation, lifecycle, migrator, proxy
      auth). Ships with a one-shot migrator that reshapes every
      existing revision; old `/file` endpoints return 410 Gone.
      Coupled: concierge `authoring-new-agents` skill rewrite, web
      app file-tree → typed editor, optional `validate_custom_tool`
      client tool for browser-side AST checking.

- [x] ~~**Persistent agent memory**~~ (Danilo for the Mnemion slice +
      v1) — see [`agent-memory.md`](agent-memory.md). Cross-session
      KV store keyed by `(agent, scope, key)` with `agent` /
      `user:<id>` / `team` / `session` scopes; surfaced by the
      cross-cutting gap in [`_APP_IDEAS.md`](_APP_IDEAS.md) (10 of 13
      candidate apps want it). **v0 (`MemoryStore` interface +
      `S3MemoryStore` impl + six `@posthog/memory-*` tools +
      MiniSearch BM25 backing `@posthog/memory-search`) ✅ shipped
      via `85c0bad0f3`.** Next round — Mnemion-adapted write
      semantics + compaction — tracked separately in
      [`agent-memory-mnemion-slice.md`](agent-memory-mnemion-slice.md).

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
      intersection to the model. Client tools shipped to date:
      `focus_tab`, `focus_file`, `focus_revision`, `focus_session`,
      `focus_spec_section`, `get_context`, `set_secret`, `toast`.
      User can toggle "Follow the agent" off without losing the
      agent's narration.

- [ ] **MCP tool approval gating — unresolved schema alignment.**
      [`runtime-mcps.md`](runtime-mcps.md) PRs 1-6 shipped the
      runtime path: agents declare `spec.mcps[]`, the runner opens
      MCP clients at session start, remote tools surface to the model
      as `<prefix>__<remoteName>`. What did NOT land: per-MCP-tool
      approval gating. Native + custom tools express this via
      `ToolRef.requires_approval` + `ToolRef.approval_policy`; MCP
      tools have no static `ToolRef` to hang the flag on (they
      materialise from `client.listTools()`). The concierge example
      bundle wants `agent-applications-destroy` etc. gated and is
      currently blocked because the schema has nowhere to express
      that. Two options on the table:

      - **Option A** — extend `McpRefExternal` with
        `tools: Array<string | { name, requires_approval, approval_policy }>`.
        Reuses `ApprovalPolicySchema`. Concierge migrates
        mechanically. Doesn't unify with `ToolRef`.
      - **Option C** — promote approvals to a top-level
        `spec.approvals.rules[]` with glob matching against the
        fully-qualified tool name (`@posthog/...` for native,
        `<prefix>__<remoteName>` for MCP). One surface for all gating.
        `ToolRef.requires_approval` becomes desugaring sugar. Bigger
        schema change; migration story needed.

      Pragmatic decision (made during the PR 6 design conversation)
      is Option A first — concierge is the only customer today, the
      dispatcher change is contained, and Option A's per-entry shape
      desugars into Option C's rule format later without a behaviour
      change. Pull Option C forward when a second MCP-heavy use case
      (Linear / GitHub / SRE bot from [`_APP_IDEAS.md`](_APP_IDEAS.md))
      forces globs like `linear__*-delete` onto the design.

      **Coupled gap:** the concierge wants
      `approvers: ['session_principal']` as the approver scope. That
      scope isn't in the v0 `ApprovalPolicySchema.approvers` enum
      (which is locked to `['team_admins']`) — covered separately in
      [`approval-gated-tools.md`](approval-gated-tools.md) §6 as a B.2
      v1 line item. PR 7 needs to pull the `session_principal`
      addition forward alongside whichever approval-on-MCP shape ships.

      Synthesis writeup with full tradeoff matrix lives in
      [`runtime-mcps.md`](runtime-mcps.md) "Open design — per-MCP-tool
      approval gating"; the `ToolRef` side is documented in
      [`approval-gated-tools.md`](approval-gated-tools.md) §3 (MCP
      gating gap).
