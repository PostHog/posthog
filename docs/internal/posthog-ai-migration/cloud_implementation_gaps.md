# Cloud agents — spec gaps and post-snapshot drift

Addendum to [`cloud_implementation.md`](./cloud_implementation.md).
That spec was reverse-engineered from the Twig monorepo (`../code/`) around 2026-05-21 and last revised 2026-06-01; Twig has kept moving.
This document records, as of an audit on 2026-06-11, (a) contract-relevant behavior the spec never documented, and (b) behavior that changed in Twig after the snapshot.

How to use it: when implementing or reviewing a migration PR that touches SSE handling, approvals, or `_posthog/*` dispatch, check the relevant section here before trusting the corresponding `cloud_implementation.md` section, and prefer verifying against current Twig code.
Items are ordered by how likely they are to bite the PostHog AI migration.

---

## 1. The spec's file index is stale — Twig refactored its layout

Every `apps/code/src/main/services/cloud-task/*` and `apps/code/src/renderer/features/sessions/service/*` citation in `cloud_implementation.md` (including the whole § 19 key-file index) points at files that no longer exist. The logic moved, largely intact, into shared packages:

| Old location (as cited in the spec)                           | Current location                                                              |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `apps/code/src/main/services/cloud-task/service.ts`           | `packages/core/src/cloud-task/cloud-task.ts`                                  |
| `apps/code/src/main/services/cloud-task/sse-parser.ts`        | `packages/core/src/cloud-task/sse-parser.ts`                                  |
| `apps/code/src/main/services/cloud-task/schemas.ts`           | `packages/core/src/cloud-task/schemas.ts`                                     |
| `apps/code/src/renderer/features/sessions/service/service.ts` | `packages/core/src/sessions/sessionService.ts` (+ sibling modules)            |
| `apps/code/src/renderer/api/posthogClient.ts`                 | `packages/api-client/src/posthog-client.ts`                                   |
| renderer conversation building                                | `packages/ui/src/features/sessions/components/buildConversationItems.ts` etc. |

The behavior documented in the spec mostly survived the move, but line numbers are meaningless and several modules picked up new behavior in transit (see §§ 3–4).
`packages/core/src/sessions/` also contains modules with no spec coverage at all, e.g. `cloudLogGap.ts` / `cloudLogGapReconciler.ts` (log-gap reconciliation) and `cloudRunIdleTracker.ts` (§ 5.2).

---

## 2. Actionable contradictions

### 2.1 `refresh_session` is not reachable through the command relay

The in-monorepo relay (`products/tasks/backend/serializers.py:1400`, `TaskRunCommandRequestSerializer.ALLOWED_METHODS`) accepts exactly `user_message`, `cancel`, `close`, `permission_response`, `set_config_option`.
`refresh_session` is **not** on the list — a `POST /runs/{id}/command/` with that method fails request validation with a 400.

This contradicts two specs:

- `cloud_implementation.md` § 6.1 lists `refresh_session` among accepted methods (it is accepted only by the **in-sandbox** JWT-authenticated `/command` endpoint, `Twig packages/agent/src/server/schemas.ts`, not by the public relay).
- `04_PROMPTS.md` § 5.4 plans MCP hot-loading via `POST /command/` with `method: "_posthog/refresh_session"`. As written that plan does not work.

Resolution needed before the hot-loading work: either add `refresh_session` to the relay's `ALLOWED_METHODS` (plus sandbox proxying for it), or route the refresh server-side (e.g. a Temporal signal/activity that calls the sandbox `/command` endpoint directly with the sandbox JWT).
Minor: `04_PROMPTS.md` § 5.4 links `../CLOUD_AGENTS_FRONTEND_SPEC.md` — a stale filename for `cloud_implementation.md`.

Related, unverified risk: `01_CONTEXT.md` plans `set_config_option("posthog_active_context", …)`.
Config ids are adapter-defined (mode / model / reasoning); whether the agent accepts an arbitrary custom config id needs verification with the agent-server before that design is relied on.

### 2.2 Permission lifecycle is persisted to the run log; the specs only handle live SSE

Since Twig `af00a58a` (2026-06-04), the agent-server persists the permission lifecycle into the run log as `_posthog/permission_request` / `_posthog/permission_resolved` notifications.
Neither appears in spec § 10.8's notification list.
On bootstrap, the Twig client scans the historical log for `permission_request` entries with no matching `permission_resolved` and re-surfaces them (`derivePendingPermissionRequests`, consumed in `packages/core/src/sessions/sessionService.ts`).

Impact on `02_CORE.md` I3 approvals: the plan ingests only the live SSE `permission_request` envelope.
Without log-based recovery, a user who reloads the page mid-approval permanently loses the approval card — the agent stays blocked (there is no agent-side timeout, per spec § 10.7) with no UI to unblock it.
The I3 `sandboxStreamLogic` work should derive pending approvals from the `logs/` bootstrap as well.

### 2.3 The SSE reconnect model is richer than the spec's three constants

`cloud_implementation.md` § 5.5 (and `02_CORE.md` § 4.2, which mirrors it) documents only `MAX_SSE_RECONNECT_ATTEMPTS = 5`, base 2s, cap 30s.
Current Twig (`packages/core/src/cloud-task/cloud-task.ts:27-34` and the reconnect path around `:640-790`, `:1050-1090`) runs three budgets plus a health rule:

- `reconnectAttempts` — transport-level drops; reset on **any** received data or keepalive.
- `streamErrorAttempts` — backend-emitted `event: error` frames counted separately; reset only on **real** data (not keepalive). Backoff uses `max(reconnectAttempts, streamErrorAttempts)`.
- `cumulativeReconnectAttempts` — global runaway cap (`MAX_CUMULATIVE_RECONNECT_ATTEMPTS = 30`) counted across the watcher's lifetime, including "clean" EOF reconnects that don't count against the per-attempt budget.
- Healthy-connection rule (`SSE_HEALTHY_CONNECTION_MS = 60_000`) — a drop after >60s connected is not penalized as a failed attempt.

The merged i2.6 SSE-resilience implementation (`sandboxStreamLogic`) was built from the spec's three-constant model and has none of these protections.
Not urgent — the simpler model fails safe (it gives up earlier, surfacing a retryable error) — but worth knowing when tuning reconnect behavior or debugging "watcher gave up" reports.

---

## 3. Undocumented wire surface

### 3.1 Undocumented `_posthog/*` notification payloads

Spec § 10.8 lists notification **names** only — payload shapes were never documented. Notifications with contract-relevant payloads (emitted from the `packages/agent` adapters: `sdk-to-acp.ts`, `claude-agent.ts`, `codex-agent.ts`, `agent-server.ts`):

- `_posthog/usage_update` — emitted in **two distinct forms** (token usage + cost, and a separate context-window breakdown); the Codex adapter's variant differs from Claude's. `02_CORE.md` § 6.3 treats this as "optional telemetry" without a shape.
- `_posthog/progress` — a group-keyed payload driving a live-mutating progress card (one card per group, steps appended/updated in place). `02_CORE.md` § 6.3 models this as a single `currentProgress` string, which under-models it.
- `_posthog/status` + `_posthog/compact_boundary` — start/end signaling for context compaction plus a post-compaction summary; Twig renders both inline.
- `_posthog/task_notification`, `_posthog/error`, `_posthog/sdk_session` — task milestones, classified errors, and adapter/session identification.
- `_posthog/resources_used` — missing from § 10.8 entirely; see § 3.2.
- `_posthog/permission_request` / `_posthog/permission_resolved` — missing from § 10.8 entirely; see § 2.2.

Field-level shapes are deliberately **not** reproduced here: they are captured as typed wire definitions in code (separate TypeScript and Python copies, validated against shared fixtures), where drift fails a test instead of going stale in prose.

Dead constants: `_posthog/branch_created` and `_posthog/session/resume` are defined in `acp-extensions.ts` and listed in spec § 10.8, but nothing in the agent package ever emits them.
`_posthog/mode_change` is likewise never emitted directly — mode changes arrive as `session/update` with `sessionUpdate: "current_mode_update"` (spec § 10.9 has this right).

### 3.2 `_posthog/resources_used` — per-turn PostHog products

Added 2026-06-04 (Twig `5a638ea4`, refined `add02dc5`): the agent tracks which PostHog products were touched in a turn (derived from MCP `exec` inner-tool calls) and emits `_posthog/resources_used` carrying the list of touched products.
Twig renders this as a persistent "PostHog resources used" bar above the composer, **not** inline in the conversation.

This is exactly the signal a Max sandbox conversation generates (every data tool is an MCP `exec` call), and the `02_CORE.md` § 6.3 dispatch table would silently ignore it ("any other `_posthog/*` → Ignore").
Decide deliberately whether PostHog AI wants the affordance; if yes, the dispatch table and `03_RICH_UI.md` need a row.

### 3.3 ACP adapter upstream syncs changed `session/update` semantics

The Claude ACP adapter synced with upstream v0.42.0 and v0.44.0 on 2026-06-11 (Twig `9512637d`, `db3f9d3d`) — after the spec snapshot:

- **`permission_denied`** now surfaces as `tool_call_update` with `status: "failed"` carrying `_meta.{ decision_reason, decision_reason_type, message }`. A renderer that only maps `failed` to a generic error loses the denial reason.
- A new **`fallback` content block type** exists (previously an unreachable-path error); arrives from gateway proxies that return consolidated, non-streamed turns.
- **Streamed-block dedup is now conditional**: assistant text/thinking blocks are dropped from the final message only if they actually streamed live (tracked per message id). Behind proxies that don't stream, blocks now arrive once in the final message instead of being dropped.

Also relevant for approvals UI: MCP tool permission requests (tool name starting `mcp__`) carry `_meta.claudeCode.toolName` so the dialog can name the server + inner tool (Twig `e0ddd01e`, 2026-06-04) — feeds the `03_RICH_UI.md` § 5 approval card and `resolveToolKey`.

---

## 4. Lifecycle behaviors the specs don't cover

### 4.1 Agent crashes mark the run failed

Since Twig `cc151980` (2026-06-02), the agent-server installs fatal handlers: uncaught exceptions / unhandled rejections PATCH the run to `failed` with `error_message: "Agent server crashed: …"` before the process dies.
Relevant to `02_CORE.md` § 4.4 error mapping (this string is what `task_run_state` / run refetch will carry) and to `05_SANDBOX.md` § 9.1, which assumes terminal transitions just happen — this is the mechanism for the crash case.
Twig also tracks a `CLOUD_STREAM_DISCONNECTED` analytics event with reconnect-budget properties; consider an equivalent for sandbox telemetry parity (`02_CORE.md` § 10).

### 4.2 Follow-up queueing and agent-readiness detection

- The relay returns `{ queued: true }` for `user_message` (it signals the Temporal workflow; `products/tasks/backend/api.py` command action). The agent-server side can also return `stopReason: "queued"` when a turn is in flight. The specs assume the signal path "just works"; what the UI shows while a follow-up is queued mid-turn is unspecified.
- Twig tracks agent readiness per run (`packages/core/src/sessions/cloudRunIdleTracker.ts`): ready after `_posthog/run_started` for **this** run, idle after `_posthog/turn_complete`. Backward-compat fallback: if `run_started` never arrives but `turn_complete` does, treat the agent as booted. Useful precedent for the `sandboxStreamLogic` `runStarted` selector.

### 4.3 Smaller items

- **Structured output trigger**: the agent-server calls `PATCH /runs/{id}/set_output/` from an `onStructuredOutput` hook driven by `task.json_schema`. Spec § 4.2 lists the endpoint but not the trigger. PostHog AI doesn't set `json_schema`, so this is context, not work.
- **Task title → LLM analytics**: the agent forwards a sanitized task title as the `x-posthog-property-task_title` gateway header, landing on `$ai_generation` events (Twig `636bb6b2`). Free attribution win for Max conversations if Task titles are set meaningfully.
- **`POST /runs/{id}/connection_token/`** (`products/tasks/backend/api.py`): mints a 24h sandbox JWT for direct sandbox connection. Internal plumbing, absent from spec § 4.2.
- **Event-ingest env vars**: `POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN` / `POSTHOG_TASK_RUN_EVENT_INGEST_STREAM_WINDOW_MS` enable optional event-ingest telemetry from the sandbox (`packages/agent/src/server/bin.ts`); absent from spec § 10.2.
- **GitHub token refresh** reads `/tmp/agent-env` live instead of `process.env` (Twig `d504c313`), and new signed-git tools `git_signed_merge` / `git_signed_rewrite` exist (`73fd6add`, `9a470ffb`) — irrelevant to PostHog AI's no-repo posture, listed so nobody re-discovers them.

---

## 5. Known gaps tracked elsewhere (listed for completeness)

Already identified before this audit; not expanded here:

- **Claude Code default tool mapping** — how the renderer maps built-in tool names (`Task`, `Skill`, `ToolSearch`, `TodoWrite`, …) to display titles/icons.
- **Code diffs** — rendering of tool-call diff content.
- **Pre-first-message transparency statuses** — sandbox activation/provisioning/loading states surfaced before the first agent message (the spec covers only the coarse `queued` / `in_progress` split behind `CloudInitializingView`, § 13.9).
- Established wire facts from implementation reviews: ACP `session/update` frames carry **no `messageId`** (fallback-id handling is the common path); `task_run_state` frames are emitted for **non-terminal** transitions too (`02_CORE.md` § 4.1's "drives Idle/Error transition" reads as terminal-only); the stream endpoint honors the **`Last-Event-ID` header first** and `?start=latest` only applies without it — a manual (non-native-EventSource) reconnect never sends `Last-Event-ID`, so lossless reconnect means full replay + content-dedup.

---

## 6. Deliberately out of scope for PostHog AI

Real spec gaps for a generic consumer of the cloud-agents contract, but irrelevant to PostHog AI's no-repo, no-desktop posture (`00_OVERVIEW.md` § 12, `05_SANDBOX.md` § 4):

- Cloud→local handoff ("continue locally") — only local→cloud is documented (§ 11); the reverse saga exists in Twig (`packages/core/src/handoff/`).
- Branch listing / repo pickers / GitHub integration endpoints used by the cloud branch selector.
- Sandbox-environment CRUD UI details beyond what § 2.7 / § 4.4 already cover.
- Run deletion (doesn't exist), inline artifact upload divergence (Twig only uses the presigned-POST flow).
