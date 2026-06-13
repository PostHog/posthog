# Sandbox streaming resilience & transparency: pre-first-message statuses + crash telemetry/affordance + richer SSE reconnect

> **Source:** outstanding_items.md § 8 "Pre-first-message transparency statuses" (§5.3) + "Sandbox disconnect/crash telemetry + crash affordance" (§4.1) + "Richer SSE reconnect model" (§2.3) · **Locus:** frontend — stream lifecycle
> **Effort:** M (joined) · **Priority:** Low-medium · **Blocks rollout:** No (rollout polish / parity)
> **Joins:** Three § 8 streaming-lifecycle items — pre-first-message status granularity, crash telemetry + a distinct crash affordance, and a richer SSE reconnect budget model — all rooted in the single keyed logic `frontend/src/scenes/max/sandboxStreamLogic.ts`. They share the stream's state machine (reconnect loop, terminal-status handling, the `_posthog/progress` ingest + `isThinking` gate), so doing them as one cohesive resilience pass avoids three serial passes over the same listeners and reducers.

## Problem

The sandbox runtime streams an agent run to the browser over an SSE `EventSource` owned by `sandboxStreamLogic`. Three resilience/transparency gaps exist today, all in that one logic:

1. **No transparency before the first agent message (§5.3).** When the user sends the first message, a Temporal workflow provisions a Modal sandbox, starts the agent server, and only then begins emitting agent output. During that window the run is `queued`/`in_progress` server-side, and the workflow _does_ emit fine-grained `_posthog/progress` notifications ("Setting up sandbox", "Starting agent"…) — but the frontend's thinking indicator that would display them is gated behind `isThinking`, which requires the `_posthog/run_started` frame. That frame only fires _after_ provisioning completes. So during the multi-second provisioning window the user sees nothing actionable: the progress notifications are received and stored but never shown, because nothing renders `currentProgress` until the agent has already started.

2. **An agent crash is invisible, and there is no disconnect/reconnect telemetry (§4.1).** When the in-sandbox agent server dies on an uncaught exception, it marks the run `failed` with `error_message: "Agent server crashed: <reason>"` (Twig's `reportFatalError`, see below) and that arrives as a `task_run_state` frame. The frontend reads that `error_message` into `handleTerminalStatus` and emits `task_run_terminated` telemetry — but it never renders the message anywhere. The thread's thinking indicator simply switches off and the composer unlocks, with no error bubble, no "the agent crashed, retry" affordance. Separately, the reconnect loop exhausts its budget and surfaces a generic "Cloud stream failed" via `handleStreamError`, but that path emits **no telemetry at all** — there is no `CLOUD_STREAM_DISCONNECTED`-equivalent event capturing how many reconnect attempts were burned, whether we were bootstrapping, etc. We are blind to stream-health in production.

3. **The SSE reconnect model is the simple version (§2.3).** PostHog has a single 5-attempt / 2s-base / 30s-cap backoff. Twig's production model adds three refinements: a _cumulative_ reconnect cap (bounds runaway clean-EOF loops that dodge the per-drop counter), a _healthy-connection rule_ (a connection that stayed open ≥60s before dropping is not counted against the budget), and a _separate stream-error budget_ (backend `event: error` frames count against their own counter, distinct from transport drops). The current model fails _safe_ — it gives up and shows a retryable error rather than looping forever — so this is the lowest-priority of the three, but on a flaky network it gives up faster than Twig and double-counts transport churn that should be forgiven.

## Current behavior (verified)

All line numbers below were re-read on 2026-06-13 against the working tree.

### Reconnect model — `sandboxStreamLogic.ts`

- Constants at **`:39-41`** (the JSDoc is `:38`; doc said `:39-52`, the actual constants are `:39-41` and the `reconnectDelayMs` helper that completes the cited range is `:49-53`):

  ```ts
  MAX_SSE_RECONNECT_ATTEMPTS = 5 // :39
  SSE_RECONNECT_BASE_DELAY_MS = 2_000 // :40
  SSE_RECONNECT_MAX_DELAY_MS = 30_000 // :41
  ```

- `reconnectDelayMs(attempt)` capped exponential backoff at **`:49-53`**.
- Reconnect loop in the `sseDropped` listener at **`:710-758`**: on a transient drop it refetches run status (`fetchRunStatus`), bails on terminal/error, else increments `reconnectAttempt` (single counter) and, if `> MAX_SSE_RECONNECT_ATTEMPTS`, calls `handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })` (**`:737-740`**); otherwise schedules `openSseForRun` after `reconnectDelayMs` via a `reconnect-backoff` disposable.
- The single `reconnectAttempt` reducer is at **`:364-373`**; reset to 0 on `sseOpened` and `bootstrapRun`. There is no cumulative counter, no healthy-connection grace, and no separate stream-error budget — a named `event: error` frame goes straight to `handleStreamError` (terminal, no retry loop) at **`:685-697`**.

### Crash / disconnect handling — `sandboxStreamLogic.ts`

- The doc's "generic crash error ~:677" resolves to the `isTaskRunStateFrame` branch of the SSE `onmessage` handler at **`:674-678`**; line **`:677`** is exactly `errorMessage: data.error_message ?? null`. A crash arrives here as a `task_run_state` frame with `status: "failed"` and `error_message: "Agent server crashed: …"`, routed to `handleTerminalStatus`.
- `handleTerminalStatus` listener at **`:798-828`**: for a terminal status it disposes the reconnect/event-source disposables, then (unless replayed from history) captures `task_run_terminated` telemetry including `error_message` (**`:818-827`**). **It never pushes a thread item** — the crash reason is captured to PostHog but not shown to the user.
- `handleStreamError` listener: there is **no listener body** for `handleStreamError` — it only feeds the `sseStatus` reducer (`:360` → `'error'`) and is observed by `maxThreadLogic` to release the streaming lock (`maxThreadLogic.tsx:942`). So a stream-error envelope unlocks the composer but renders **nothing** in the thread. The only path that pushes a visible error item is `_posthog/error` notifications → `pushErrorItem` (`:887-890`).
- `mapHttpStatusToStreamError` at **`:65-78`** maps HTTP status → `{ errorTitle, retryable }`.
- The thread renders `item.type === 'error'` items only (`Thread.tsx:182-188`), and the thinking indicator at `Thread.tsx:191` (`isThinking && <SandboxThinkingIndicator progress={currentProgress} />`).

### Pre-first-message statuses — server + frontend

- The provisioning workflow already emits `_posthog/progress` for each setup phase: `products/tasks/backend/temporal/process_task/workflow.py:379` ("Setting up sandbox"), `:407`/`:409` ("Starting agent"/"Started agent"), plus clone/checkout for repo runs at `:674-709`. These go through `emit_progress_activity` → `_posthog/progress`.
- The frontend ingests `_posthog/progress` at **`sandboxStreamLogic.ts:882-886`** → `setCurrentProgress`.
- But `currentProgress` is only rendered when `isThinking` is true (`Thread.tsx:191`), and `isThinking` (selector at **`:576-580`**) requires `runStarted`, which is set only by the `_posthog/run_started` frame (`:856-877`). Before `run_started`, `isThinking` is `false`, so the provisioning-phase progress is **received and stored but never shown**.
- `currentRunStatus` reducer at **`:387-396`** tracks `queued`/`in_progress`/terminal, but `Thread.tsx` does not render it pre-first-message (no surface consumes `currentRunStatus` for a status line). The `stage` field on `task_run_state` (`sandboxWireTypes.ts:45` — `stage?: string | null` on `TaskRunStateFrame`; cf. `TaskRun.stage`, `products/tasks/backend/models.py:590-595`, serialized into the wire frame at `models.py:981`) is **dropped entirely** on the frontend — `stage` is referenced nowhere in `sandboxStreamLogic.ts`.

### Twig reference implementation (the port target)

- `Twig/packages/core/src/cloud-task/cloud-task.ts` — the full reconnect model:
  - Constants at **`:27-31`**: `MAX_SSE_RECONNECT_ATTEMPTS = 5`, `MAX_CUMULATIVE_RECONNECT_ATTEMPTS = 30`, base `2_000`, cap `30_000`, `SSE_HEALTHY_CONNECTION_MS = 60_000`.
  - Three counters on `WatcherState` (**`:99-101`**): `reconnectAttempts`, `streamErrorAttempts`, `cumulativeReconnectAttempts`.
  - Healthy-connection rule in the `connectSse` catch at **`:715-739`**: `wasHealthyStream = streamWasEstablished && Date.now() - connectedAt >= SSE_HEALTHY_CONNECTION_MS`; if healthy, the transport reconnect attempt is _not_ counted (`countReconnectAttempt: !isBackendError && !wasHealthyStream`).
  - Separate stream-error budget: a backend `event: error` frame throws `BackendStreamError` (**`:756-761`**) and increments `streamErrorAttempts`; a real data event clears `streamErrorAttempts` _and_ `cumulativeReconnectAttempts` (**`:779-782`**); a keepalive clears only the transport `reconnectAttempts` (**`:767`**).
  - `scheduleReconnect` at **`:1035-1107`**: increments cumulative, fails on `cumulative > 30` (**`:1057-1067`**), fails on `max(reconnectAttempts, streamErrorAttempts) > 5` (**`:1071-1087`**), backs off using whichever budget the error type maps to.
  - Telemetry: `failWatcher` at **`:991-1033`** fires `CLOUD_STREAM_DISCONNECTED` with `{ task_id, run_id, team_id, error_title, retryable, reconnect_attempts, stream_error_attempts, cumulative_reconnect_attempts, was_bootstrapping }` (event def `Twig/packages/shared/src/analytics-events.ts:866`; properties interface `:239-249`).
- `Twig/packages/agent/src/server/agent-server.ts:613-641` — `reportFatalError`: on an uncaught exception / unhandled rejection the in-sandbox agent server calls `updateTaskRun(..., { status: "failed", error_message: \`Agent server crashed: ${errorMessage}\` })`(**`:618-625`**). The comment at **`:605-611`** explicitly notes the desktop client otherwise "just sees the stream stop and shows a generic 'Cloud stream disconnected'". This is the producer of the crash`error_message` PostHog receives — it is already wired in the agent server that ships in the sandbox image; **no PostHog-side server change is needed** for the crash string to arrive.

## Approach

Do all three as one pass over `sandboxStreamLogic.ts` (plus a small `Thread.tsx` render addition and one telemetry event). Sequenced by priority/independence: **(A) crash affordance + telemetry**, then **(B) pre-first-message statuses**, then **(C) richer reconnect model**.

### A. Crash/disconnect telemetry + crash affordance (highest of the three)

Two distinct user-visible failures need distinct treatment, and both need telemetry:

1. **Agent crash** — terminal `failed` status carrying `error_message` (often `"Agent server crashed: …"`). In `handleTerminalStatus`, when the status is `failed` and an `errorMessage` is present and not replayed-from-history, push a thread error item so the user sees _why_ the run ended, instead of the indicator silently vanishing. Detect the crash shape (`errorMessage.startsWith("Agent server crashed")`) to render a distinct, friendlier affordance ("The agent encountered a fatal error and stopped. You can send a new message to try again.") while still showing the raw reason in a secondary line; non-crash `failed` runs render the raw `errorMessage` as before. Reuse the existing `error` thread-item type and `pushErrorItem` — do **not** invent a new render path; if the crash needs distinct styling, add a `variant: 'crash' | 'error'` field to the error `ThreadItem` and branch in `Thread.tsx:182-188`.

2. **Stream disconnect (reconnect budget exhausted)** — add a `handleStreamError` _listener_ that (a) pushes a visible error item carrying `errorTitle`/`errorMessage` so the composer-unlock isn't silent, and (b) captures a `sandbox_stream_disconnected` telemetry event mirroring Twig's `CLOUD_STREAM_DISCONNECTED` shape: `{ conversation_id, trace_id, run_id, task_id, error_title, retryable, reconnect_attempts, stream_error_attempts, cumulative_reconnect_attempts, was_bootstrapping, execution_type: 'sandbox' }`. The `*_attempts` and `was_bootstrapping` fields come from the reducers/cache populated in part C (before C lands, populate the ones we already have: `reconnect_attempts` from `reconnectAttempt`, the rest `0`/`false`).

Telemetry naming follows the existing snake_case `posthog.capture('task_run_terminated', …)` convention already in this file (`:818`, `:864`, `:1020`, `:766`) — these events are emitted directly via `posthog.capture` from the frontend (the SSE bypasses Django), correlated by `conversation_id` (props) + `trace_id` (the `traceId` reducer). Do **not** route this through a Django serializer/viewset — it is pure frontend telemetry, so neither `/improving-drf-endpoints` nor `/adopting-generated-api-types` applies here.

**Rejected alternative:** adding a backend `CLOUD_STREAM_DISCONNECTED` capture in the relay activity. The disconnect is a client-side condition (the browser's reconnect budget), invisible to the relay, so it must be captured client-side like every other event in this logic.

### B. Pre-first-message transparency statuses

The server already emits everything we need — the gap is purely that the frontend won't _render_ progress until `run_started`. Fix the render gate, not the data:

1. Introduce a derived "phase" selector, e.g. `streamPhase: 'provisioning' | 'thinking' | 'idle'`, computed from `currentRunStatus`, `runStarted`, `sseStatus`, and `turnComplete`. `provisioning` = SSE open (or connecting/queued) and `!runStarted` and not terminal; `thinking` = the existing `isThinking` condition; else `idle`.
2. In `SandboxThread` (`Thread.tsx`), render a provisioning indicator whenever `streamPhase === 'provisioning'`, driven by `currentProgress` (the already-ingested `_posthog/progress` label) with a sensible fallback ("Setting up your workspace…"). This reuses `SandboxThinkingIndicator`'s spinner+label component — extract a shared `StreamStatusLine` or pass the phase in. Keep `isThinking` for the post-`run_started` thinking line unchanged.
3. Optionally fold the `stage` field from `task_run_state` into a `currentStage` reducer so a future richer status surface (G6) can show "research / plan / build" — but for PostHog AI runs `stage` is generally unset, so treat this as a thin, optional addition, not a requirement. Recommend wiring the reducer (cheap, no render) so G6 can consume it without re-touching this file.

This is the cleanest cut because **no new server lifecycle phases are needed** — the available server-side phases are already enumerated by the `_emit_progress` calls in `workflow.py` (sandbox setup, agent start, and — for repo runs only, irrelevant to PHAI — clone/checkout). The "fine-grained provisioning steps" the triage doc asks for already exist on the wire; we just stop hiding them.

**Cross-reference G1 (small-data-sandboxes):** G1 may change provisioning timing/labels and could add a tier signal. This plan only _renders_ whatever `_posthog/progress` labels the workflow emits, so it is forward-compatible with G1 — no coordination needed beyond "don't hardcode the label strings; render whatever the wire sends."

**Cross-reference G6 (notification rendering):** G6 owns rendering of `_posthog/status`, `_posthog/compact_boundary`, etc. The provisioning status line here is a _different_ surface (pre-first-message, driven by `_posthog/progress` + run status). Keep them distinct: this plan does not render `_posthog/status`; G6 does not render the provisioning phase. If G6 builds a shared status-line component, this plan should reuse it rather than duplicate.

### C. Richer SSE reconnect model (lowest of the three)

Port Twig's three refinements into the existing kea reducers/cache. The current single-`EventSource`-per-logic shape maps cleanly:

1. **Cumulative cap.** Add `cumulativeReconnectAttempt` reducer; increment in `sseDropped` regardless of whether the per-drop counter increments; fail (via `handleStreamError`) once `> MAX_CUMULATIVE_RECONNECT_ATTEMPTS` (30).
2. **Healthy-connection rule.** Record `cache.sseConnectedAtMs` in `sseOpened`; in `sseDropped`, compute `wasHealthy = connectedAtMs && Date.now() - connectedAtMs >= SSE_HEALTHY_CONNECTION_MS` (60s) and skip incrementing `reconnectAttempt` when healthy (still increment cumulative).
3. **Separate stream-error budget.** Today a named `event: error` frame is terminal (`:685-697`). Twig treats a _backend_ stream-error frame as retryable against `streamErrorAttempts`. Decide (see open questions) whether to adopt that — it materially changes behavior (a backend error frame would now retry instead of failing fast). Recommend the conservative cut: keep named `event: error` envelopes terminal (they carry their own `retryable` flag and `errorTitle`), and only add the cumulative cap + healthy-connection rule, which are pure safety improvements with no behavior regression. Adopt the separate stream-error budget only if we observe backend error frames that are in fact transient.

Because this logic is one `EventSource` per keyed logic (not Twig's multi-subscriber `WatcherState` map), we do **not** port the subscriber-count/snapshot machinery — only the three counter refinements.

## Implementation steps

1. **(A) Stream-disconnect telemetry + visible error.** Add a `handleStreamError` listener in `sandboxStreamLogic.ts` that pushes an error thread item (reuse `pushErrorItem` or a new `pushErrorItem(message, variant)`) and captures `sandbox_stream_disconnected` with the attempt counters + `was_bootstrapping` + the standard `conversation_id`/`trace_id`/`run_id`/`task_id`/`execution_type` correlation fields. **NOTE on `was_bootstrapping`:** the existing `cache.bootstrapReplay` flag is _not_ usable here — it is set `true` only inside the synchronous history-replay `forEach` (`:608-613`) and reset to `false` in the same tick, so it is always `false` by the time an async drop/error fires. To mirror Twig's persistent `watcher.isBootstrapping`, add a _new_ boolean (`cache.isBootstrapping` set `true` at `bootstrapRun` start and cleared on first `sseOpened`/`run_started`, or a reducer) — or, before C lands, just emit `was_bootstrapping: false`.
2. **(A) Crash affordance.** In `handleTerminalStatus`, when `status === 'failed' && errorMessage && !replayedFromHistory`, push a thread error item; branch the message/variant on `errorMessage.startsWith('Agent server crashed')`. Keep the existing `task_run_terminated` capture unchanged. If distinct styling is wanted, extend the `error` `ThreadItem` with an optional `variant` and branch in `Thread.tsx:182-188`.
3. **(B) Provisioning phase.** Add a `streamPhase` selector; render a provisioning status line in `SandboxThread` when phase is `provisioning`, driven by `currentProgress`. Extract the spinner+label out of `SandboxThinkingIndicator` into a shared component if it makes the two surfaces cleaner. Optionally add a `currentStage` reducer fed from the `task_run_state` frame's `stage` (and the non-terminal `task_run_state` branch — see note below).
4. **(B) Non-terminal `task_run_state` — already covered for status; only `stage` needs new wiring.** Note that `currentRunStatus` is _already_ populated for `queued`/`in_progress`: `onmessage` dispatches `handleTerminalStatus({ status, … })` for **every** `task_run_state` frame (`:674-678`), and the `currentRunStatus` reducer (`:387-396`) records whatever `status` it's handed — only the _listener_ body early-returns for non-terminal (`:801-803`). So the `streamPhase` selector can read `currentRunStatus` with no new routing. The only thing missing on the wire is `stage`, which is dropped entirely — so the optional `currentStage` reducer is the _only_ new dispatch the non-terminal frame needs (add a `setCurrentStage` action fed from `data.stage` at `:674-678`). Keep terminal routing unchanged.
5. **(C) Reconnect counters.** Add `cumulativeReconnectAttempt` reducer + `MAX_CUMULATIVE_RECONNECT_ATTEMPTS`/`SSE_HEALTHY_CONNECTION_MS` constants; record `cache.sseConnectedAtMs` in the `sseOpened` listener; apply the healthy-connection skip + cumulative cap in `sseDropped`. Update `reconnectDelayMs` callers if the chosen-budget backoff differs.
6. **(C, conditional)** If adopting the separate stream-error budget: add a `streamErrorAttempt` reducer and reclassify named `event: error` frames as retryable. Otherwise leave the named-error path terminal.
7. **Tests.** Extend `sandboxStreamLogic.test.ts` (see Testing) — it already has a `MockEventSource` with `emitDrop`/`emitErrorFrame`/`emitMessage` and uses fake timers for backoff.
8. **Lint/types.** `pnpm --filter=@posthog/frontend typescript:check` and `format`. All new functions need explicit return types; keep business logic in the kea logic (no React hooks) per CLAUDE.md.

## Files to change

| Path                                                  | Change                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `frontend/src/scenes/max/sandboxStreamLogic.ts`       | New `handleStreamError` listener (push error item + `sandbox_stream_disconnected` telemetry); crash branch in `handleTerminalStatus`; `streamPhase` selector; optional `currentStage`/non-terminal `task_run_state` routing; new reconnect constants + `cumulativeReconnectAttempt` reducer + healthy-connection cache; optional `streamErrorAttempt`. |
| `frontend/src/scenes/max/Thread.tsx`                  | Render a provisioning status line in `SandboxThread` (phase = `provisioning`); branch the `error` item render on optional `variant` for the crash affordance; possibly extract a shared spinner+label component.                                                                                                                                       |
| `frontend/src/scenes/max/types/sandboxStreamTypes.ts` | Add optional `variant` to the `error` `ThreadItem` (only if distinct crash styling is chosen). NOTE: the triage doc's `sandboxWireTypes.ts` path is actually `frontend/src/scenes/max/types/sandboxWireTypes.ts`; `ThreadItem` lives in the sibling `sandboxStreamTypes.ts`.                                                                           |
| `frontend/src/scenes/max/sandboxStreamLogic.test.ts`  | Tests for crash affordance, stream-disconnect telemetry + error item, cumulative cap, healthy-connection grace, and (if adopted) stream-error budget.                                                                                                                                                                                                  |

No backend changes. No serializer/viewset/`lib/api` type changes (`mapHttpStatusToStreamError` and `fetchRunStatus` already use the existing `api.tasks.runs.*`).

## Decisions & open questions

1. **Adopt the separate stream-error budget (C3) now, or only cumulative-cap + healthy-connection?**
   _Recommendation:_ ship only the cumulative cap + healthy-connection rule now (pure safety, no behavior regression). Keep named `event: error` frames terminal — they carry their own `retryable` flag. Add the stream-error budget later only if production shows transient backend error frames. (Lowest priority; the simple model already fails safe.)

2. **Distinct crash styling, or just render the crash `error_message` as a normal error item?**
   _Recommendation:_ add a minimal `variant: 'crash'` on the error `ThreadItem` and a friendlier copy line for crashes, but keep it a one-field branch in the existing render path — don't build a separate component. The crash is the most actionable failure (retry usually works), so a clear "the agent crashed, send again" beats a raw stack-trace-ish line.

3. **Should `handleStreamError` push a visible error item, given it already unlocks the composer?**
   _Recommendation:_ yes. Today the composer silently unlocks with no explanation. A retryable "Lost connection — send your message again" line is the parity behavior and costs almost nothing.

4. **Telemetry event name.** `sandbox_stream_disconnected` (snake*case, matching `task_run_terminated`/`task_run_started`/`tool_call_completed` already in this file) vs. mirroring Twig's display name.
   \_Recommendation:* `sandbox_stream_disconnected`, with `execution_type: 'sandbox'`, so it sits alongside the existing sandbox telemetry and is filterable the same way.

5. **`currentStage` / non-terminal `task_run_state` routing — in scope here or deferred to G6?**
   _Recommendation:_ wire the cheap reducer here (it's the same `task_run_state` frame this logic already parses) but render the stage only if/when G6's status surface lands. The provisioning _progress_ line (driven by `_posthog/progress`) is the must-have for §5.3 and does not depend on `stage`.

6. **Should the provisioning line reuse G6's status-line component if G6 lands first?**
   _Recommendation:_ yes — coordinate on a shared `StreamStatusLine`. Whichever plan lands first owns the component; the other reuses it. Avoid two near-identical spinner+label widgets.

## Dependencies & sequencing

- **Within this pass:** A → B → C. A (crash + disconnect telemetry/affordance) is the highest-value and most independent; it touches only listeners + one render branch. B (provisioning statuses) is independent of A but shares the `Thread.tsx` `SandboxThread` edit, so do it right after. C (reconnect model) is the riskiest behavior change and lowest priority — do it last, behind the conservative-cut decision, so a regression there doesn't hold up A/B.
- **Cross-references (do not duplicate):**
  - **G1-small-data-sandboxes.md** — may change provisioning labels/timing and add a tier signal. This plan renders whatever `_posthog/progress` labels arrive, so it is forward-compatible; do not hardcode label strings.
  - **G6-sandbox-notification-rendering.md** — owns `_posthog/status`/`_posthog/compact_boundary`/`resources_used` rendering. This plan owns only the pre-first-message _progress_ line and the crash/disconnect error items. Share a status-line component; do not render G6's notifications here.
  - **G2-cancel-bail-button.md** — owns composer button state on cancel. This plan's `handleStreamError`/`handleTerminalStatus` listeners already release the streaming lock (`maxThreadLogic.tsx:940-942`); ensure the new error-item pushes don't re-lock the composer or interfere with G2's button-state fix. Verify with G2 that surfacing a crash/disconnect item leaves the composer in `send`, not `stop`.

## Testing

`sandboxStreamLogic.test.ts` already mounts the logic with a `MockEventSource` (`emitOpen`/`emitMessage`/`emitDrop`/`emitErrorFrame`) and Jest fake timers for backoff — extend it (single top-level `describe`, per repo jest convention):

- **Crash affordance (A):** emit a `task_run_state` `{ status: 'failed', error_message: 'Agent server crashed: boom' }`; assert a `threadItems` error item is pushed with the crash variant/copy, the existing `task_run_terminated` capture still fires, and the composer-unlock path still runs. Also assert a plain `failed` without a crash prefix renders the raw message.
- **Stream-disconnect telemetry (A):** drive `sseDropped` past `MAX_SSE_RECONNECT_ATTEMPTS` (advance fake timers across attempts) until `handleStreamError` fires; assert a `posthog.capture('sandbox_stream_disconnected', …)` with the correct attempt counters + `was_bootstrapping`, and a visible error item.
- **Provisioning phase (B):** open SSE, emit a `_posthog/progress` before any `_posthog/run_started`; assert `streamPhase === 'provisioning'` and `currentProgress` is set; then emit `run_started` and assert phase flips to `thinking`. (Render assertion is light — the selector is the unit under test; a focused `Thread.tsx` jest render is optional.)
- **Reconnect refinements (C):** (i) cumulative cap — force ≥31 clean-EOF/drop cycles where the per-drop counter would otherwise stay low, assert `handleStreamError` fires on the cumulative bound; (ii) healthy-connection — `sseOpened`, advance ≥60s, `emitDrop`, assert `reconnectAttempt` did _not_ increment but a reconnect was still scheduled; (iii) if adopted, stream-error budget — `emitErrorFrame` against its own counter.
- Run via `hogli test frontend/src/scenes/max/sandboxStreamLogic.test.ts`. No backend/query-count tests (frontend-only). A Playwright pass is not warranted for this polish; rely on the logic unit tests.

## Rollout / flagging

- The crash affordance + provisioning status line are pure UX improvements behind the existing sandbox-runtime gate (`conversation.agent_runtime === 'sandbox'`) — no new feature flag needed; they only render for sandbox conversations, which are already flag-gated upstream.
- The new `sandbox_stream_disconnected` telemetry is additive; verify it appears in PostHog after deploy and wire it into the existing sandbox stream-health dashboards (it is the missing `CLOUD_STREAM_DISCONNECTED`-equivalent the triage doc calls out).
- The reconnect-model change (C) is the only behavior-affecting piece; ship it last and watch `sandbox_stream_disconnected` rates before/after to confirm the cumulative cap + healthy-connection rule reduce premature give-ups without introducing runaway loops.

## Effort & risk

**Effort: M (joined).** A is S; B is S–M (one selector + one render surface, the data already exists); C is M (counter bookkeeping + careful test coverage). Combined ~M because they share the same file and tests.

**Risks:**

- **C is the only regression risk** — getting the three counters' reset/increment rules wrong could either loop forever (cumulative cap mis-applied) or give up too early. Mitigated by porting Twig's exact reset semantics (keepalive clears transport budget only; real data clears all; healthy connection forgives) and the targeted tests. The conservative cut (skip the stream-error budget) reduces this further.
- **B render coordination with G6** — risk of two near-duplicate status lines if G6 lands in parallel; mitigated by the shared-component decision.
- **A composer-state interaction with G2** — pushing a visible error item must not re-trigger the stop/bail button state; verify against G2's fix.
- Low overall: none of this blocks rollout, and the current behavior already fails safe.
