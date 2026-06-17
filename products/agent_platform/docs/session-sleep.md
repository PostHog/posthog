# Session sleep — the `@posthog/meta-sleep` native tool

## What it is

A control-flow native tool an agent calls to suspend its own session for up to
**60 minutes**. Instead of holding the runner slot and connection open, it
checkpoints the session, releases every resource (runner slot, sandbox, model
connection), and parks the session in a new `waiting` state with a `wake_at`
timestamp. The janitor's existing sweep flips the session back to `queued` once
`wake_at` passes; a runner then claims it via the normal path and the model
resumes with a system notice describing how long it actually slept.

This is a "checkpoint + release + scheduled re-entry", **not** a frozen process.

## Why not just `await sleep(ms)` in a normal tool

A normal data tool that blocked would pin a runner slot (concurrency is small)
and the sandbox for the whole duration — exactly what we're avoiding. `sleep`
therefore behaves like the existing meta control-flow tools
(`meta-end-turn` / `meta-end-session`): the runner intercepts it, terminates the
turn, and re-queues. Cost while asleep is ~zero (one parked DB row).

## The two precedents it builds on

1. **Control-flow ("meta") tools** — `agent-tools/src/tools/meta.ts` +
   `makeControlFlowTool` in `agent-runner/src/loop/build-agent-tools.ts`. The
   runner returns `{ details: { control }, terminate: true }`; the driver maps
   `details.control` → a `RunOutcome`; the worker maps that → a session state.
   `sleep` adds a third `MetaControl` kind alongside `end_turn` / `close`.

2. **Re-queue + replay-on-resume** — `decideElevationRequest` and the approval
   flow re-queue a session and inject a steering message that the driver's
   `getSteeringMessages` drains at turn start. `sleep` reuses the same
   resume shape: park → wake → inject a notice → model continues.

## The one genuinely new piece

The queue had **no deferred eligibility**. The hot claim stays untouched
(`WHERE state = 'queued' ORDER BY created_at`). Instead we add a distinct
`waiting` state plus a `wake_at` column, and the janitor sweep flips
`waiting → queued` when `wake_at <= now`. Keeping the hot path unchanged and
making "asleep" an observable state (visible in the console / live-sessions
panel — note the queue docs already referenced a `waiting` live state) is the
deliberate trade-off vs. filtering `wake_at` in the claim query. ~30s wake
granularity is negligible against minute-scale sleeps.

## Lifecycle

1. Model calls `@posthog/meta-sleep { duration_minutes, reason? }`.
   `duration_minutes` is clamped to `[1, 60]` in the runner (TypeBox `returns`
   isn't enforced at runtime, so we clamp in code).
2. Runner intercepts it (`makeControlFlowTool`), returns control
   `{ kind: 'sleep', wakeAt, sleptAt, requestedMinutes, reason? }` +
   `terminate: true`. The tool's own `tool_result` is persisted against its
   `tool_use` id (same `message_end` path `end_turn` uses) so the
   assistant/tool-result pair is complete — no orphaned `tool_use` on resume.
3. Driver outcome derivation: `control.kind === 'sleep'` →
   `RunOutcome { state: 'waiting', wakeAt, sleptAt }`, and emits a `sleeping`
   SSE event.
4. Worker persists `state='waiting'`, `wake_at`, `slept_at`. Sandbox released in
   the normal `finally` — no special path.
5. **Timer wake**: janitor `sweepOnce` calls `queue.wakeReadyWaiting(now)` →
   `UPDATE … SET state='queued' WHERE state='waiting' AND wake_at <= now`.
   `wake_at`/`slept_at` are left on the row so the driver can compute the delta.
6. **Early wake via `/send`**: the existing `enqueueOrResume` resume path treats
   any non-`closed`/`failed` session as resumable — it appends the message to
   `pending_inputs` and sets `state='queued'`. A `waiting` session is thus woken
   immediately by an inbound message with **no enqueue.ts change**.
7. Claim returns the session (state → running) and **clears `wake_at`/`slept_at`
   in the DB while returning their pre-claim values in-memory**, so the driver
   can build the notice and a later terminal state has them clean.
8. Driver, at turn start, sees `slept_at` set → injects a one-shot
   **system wake notice** into `getSteeringMessages`: requested minutes, actual
   minutes slept, and whether it was woken early (by a message) or its timer
   elapsed. The model then decides to continue or sleep again.

## Sandbox state does NOT survive sleep

On release the sandbox is destroyed and a fresh one is acquired on resume; only
`conversation` + `pending_inputs` persist. So `sleep` is for backoff / polling /
scheduled follow-ups / waiting on an async process — **not** "keep my
half-edited working tree and resume editing." The tool description tells the
model to persist anything durable (git, memory, tabular store) before sleeping.

## Opt-in

`@posthog/meta-sleep` is registered and intercepted as control-flow, but it is
**not** always-on: an agent only gets it if its spec lists the tool. Flipping it
to always-on later is a one-line change (add the id to
`ALWAYS_ON_NATIVE_TOOL_IDS`).

## Files

- `agent-tools/src/tools/meta.ts` — `sleepTool` + `MAX_SLEEP_MINUTES` +
  `MAX_CUMULATIVE_SLEEP_MINUTES`.
- `agent-tools/src/registry.ts` — register + re-export both caps.
- `agent-runner/src/loop/build-agent-tools.ts` — `MetaControl` sleep kind,
  `CONTROL_FLOW_IDS`, `makeControlFlowTool` clamp + control + cumulative-cap
  deny/clamp (reads `deps.session.slept_total_minutes`).
- `agent-runner/src/loop/driver.ts` — `RunOutcome` waiting kind (carries
  `requestedMinutes`), outcome derivation, wake-notice injection.
- `agent-runner/src/workers/worker.ts` — outcome → `waiting` state persist +
  `slept_total_minutes` accrual.
- `agent-ingress/src/enqueue/enqueue.ts`, `triggers/chat.ts`, `triggers/mcp.ts`
  — reset `slept_total_minutes` to 0 on fresh external input.
- `agent-shared/src/spec/spec.ts` — `waiting` state, `wake_at`/`slept_at`/
  `slept_total_minutes` fields.
- `agent-shared/src/persistence/queue.ts` — `LIVE_SESSION_STATES`,
  `wakeReadyWaiting`.
- `agent-shared/src/persistence/pg-queue.ts` — SELECT/insert/update/claim-clear,
  `rowToSession`, `wakeReadyWaiting`.
- `agent-shared/src/persistence/test-reset.ts` — test DDL columns + index.
- `agent-shared/src/runtime/bus.ts` — `sleeping` event kind.
- `agent-janitor/src/sweep.ts` — Policy 1b: wake ready waiting sessions.
- `agent-janitor/src/server.ts` — `wake_at` on the session list/live summaries.
- `backend/presentation/views.py` — `waiting` in the state enum, `wake_at` on the
  session serializers, `liveCount` doc.
- `backend/models.py` + migrations `0004` (`wake_at`/`slept_at` + index) and
  `0005` (`slept_total_minutes`).
- `agent-tests/src/cases/session-sleep.test.ts` — full lifecycle e2e coverage.

## Guardrails

- **Single-sleep cap**: 60 min, clamped in the runner
  (`MAX_SLEEP_MINUTES`).
- **Cumulative-sleep cap**: `MAX_CUMULATIVE_SLEEP_MINUTES` (7 days) bounds a
  self-scheduling `sleep → wake → sleep` runaway. `agent_session.slept_total_minutes`
  accrues the requested duration each time the session parks. Once the budget is
  exhausted the runner **denies** the sleep with a non-terminating result
  (`{ sleep_denied: true, reason: 'cumulative_sleep_budget_exhausted' }`) so the
  model continues or ends instead of parking; the final sleep before the cap is
  clamped to the remaining budget rather than denied. The counter **resets to 0
  on fresh external input** — every resume path that appends a real message
  (chat `/send`, the `external_key` resume in `enqueueOrResume`, MCP
  continuation) zeroes it, so only a purely autonomous loop accrues toward the
  cap. A timer self-wake (`wakeReadyWaiting`) deliberately does **not** reset it.
- `waiting` is excluded from the idle-`completed` close sweep (that sweep
  targets `state='completed'` only) and from the stuck-`running` reaper.
- `waiting` is added to `LIVE_SESSION_STATES` so rollups count it as live.

## Observability

`waiting` is a first-class session state across the read surface: the Django
`AgentSession.state` enum (`_AGENT_SESSION_STATE_VALUES`), the session-list /
session-detail / fleet-live serializers, and the regenerated frontend +
MCP types all know it. The session summary, detail, and fleet-live payloads
carry `wake_at` (populated while parked, null otherwise) so a console can render
a "sleeping until &lt;wake_at&gt;" affordance. The `liveCount` rollup counts
`waiting` sessions as live.
