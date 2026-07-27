# Janitor

Operational service: internal HTTP for Django (session lifecycle, approval decisions, revision authoring/freeze), the periodic queue sweep, and cron firing. It doubles as the agent-admin surface because it already has DB + bundle store access.

## invariants

- freeze-validate-lockstep
- approval-wire-consumption
- sweep-bounded-retries

## works when

- typechecks
- boundary "freeze-validate-lockstep" at validateRevisionBundle
- passes test "reports missing_entrypoint when agent.md is absent"
- passes test "catches unknown native tool ids and resolves valid ones"
- passes test "flags a manual model the gateway does not serve; passes one it does"
- passes test "rejects a required client tool when a webhook trigger is also configured"
- passes test "flags a malformed cron schedule"
- boundary "approval-wire-consumption" at buildJanitorApp via guard "approval routes never bypass the shared serializer"
- boundary "sweep-bounded-retries" at sweepOnce
- passes test "poison-pills a stuck running session after maxRetries re-queues"

## why

freeze-validate-lockstep: `validateRevisionBundle` is the single freeze-time gate a revision must pass before promotion to `ready`, and its checks deliberately mirror the paths the runtime would otherwise handle by silently degrading rather than rejecting — an unregistered native tool id is dropped from the toolset in `build-agent-tools.ts` (agent-runner) instead of erroring, a missing `agent.md` renders as a placeholder string in `system-prompt.ts`, and a sub-minute cron schedule would otherwise rely on the runtime's `MAX_FIRINGS_PER_TICK` backstop instead of failing outright. Freezing converts each of those silent runtime degradations into an explicit, author-visible error at promotion time, so a broken revision can't ship as a mysteriously half-working agent. The oracle pins five representative checks (missing entrypoint, unregistered native tool, a rejected model, a required client tool without a chat trigger, and a malformed cron schedule) as passing behavioral tests.
approval-wire-consumption: every janitor route that returns an approval row (`GET /approvals`, `GET /fleet/approvals`, `GET /approvals/:id`) must go through the shared `serializeApprovalRequest`, the one function that resolves `approver_scope.type` via `effectiveApprovalType` (declared `approval-wire-resolved` in agent-shared's `Persistence.spec.md`). A hand-rolled response bypassing it would ship the raw, unresolved scope and reintroduce the undefined-type regression that boundary was written to prevent one layer down. `serializeApprovalRequest` itself is defined in agent-shared, outside this package's own symbol graph, so this boundary anchors at `buildJanitorApp` — the one function that wires every approval route — and backs it with a source-property guard: no non-test file in the janitor's own source references `approver_scope` directly, the field a hand-rolled shape would have to touch.
sweep-bounded-retries: `sweepOnce` is the sole caller of `queue.reapStuckRunning` in the janitor, and it always supplies a bounded `maxRetries` (default 3) rather than re-queuing a stuck session unconditionally. The bound is enforced atomically inside `PgSessionQueue.reapStuckRunning`'s `retry_count < maxRetries` / `>= maxRetries` predicates, so a crash-looping session is poisoned (failed) instead of being re-queued forever and re-running its side effects on every sweep tick. The oracle exercises the real Postgres-backed queue across three consecutive sweeps and asserts the exact tick where the session flips from requeue to poison — a non-proxy check against real enforcement.
