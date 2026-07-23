# Persistence

Postgres-backed stores for the agent runtime, including the approval-gated tool-call store. Approval authority (who may clear a gated call) and the wire shape the console/ingress consume are resolved here through a single owner.

## invariants

- approval-authority-totality
- approval-wire-resolved
- approval-state-vocabulary
- session-single-owner
- wake-not-lost-for-completed
- terminal-no-resurrection

## works when

- typechecks
- boundary "approval-authority-totality" at effectiveApprovalType via test "approval-authority totality"
- boundary "approval-wire-resolved" at serializeApprovalRequest
- passes test "resolves a legacy approvers"
- boundary "approval-state-vocabulary" at APPROVAL_REQUEST_STATES via test "spec generated artifacts"
- boundary "session-single-owner" at PgSessionQueue
- passes test "a /send against a running session must not make it claimable by a second worker"
- boundary "wake-not-lost-for-completed" at PgSessionQueue
- passes test "worker finalize must not strand a pending input that arrived after the last drain"
- passes test "closeIfIdle re-queues instead of closing when an undrained input landed"
- passes test "cancel-reopen with an undrained input re-queues"
- boundary "terminal-no-resurrection" at FINAL_SESSION_STATES
- passes test "a wake racing termination must not resurrect"
- passes test "a late approval decision does not change"
- passes test "finalize with outcome"
- passes test "expires the approval and appends no marker"
- passes test "findByExternalKey prefers a live session"

## why

approval-authority-totality: `effectiveApprovalType` decides WHO may clear a gated tool call — `principal` (the end user, weaker gate) or `agent` (the owner via console, stronger gate). Recognition of a concrete authority is derived from `ApprovalTypeSchema` (not a hardcoded `=== 'agent' || === 'principal'`), so a new authority added to the enum is honored instead of silently downgrading to the weakest gate. The oracle enumerates `ApprovalTypeSchema.options` — the same source that defines the vocabulary — and asserts each round-trips, with a floor so it can't pass vacuously if the projection collapses.
approval-wire-resolved: every surface that gates on approval authority (janitor read routes, the runner's `approval_required` SSE frame, the ingress decision API) must consume a resolved `approver_scope.type`, never the raw legacy `approvers[]` shape. `serializeApprovalRequest` is the single serializer that resolves it via `effectiveApprovalType`; a hand-rolled copy that returned the scope raw had drifted and left legacy rows with an undefined type. The oracle asserts a legacy scope is resolved (not passed raw), which is the contract the Django decide gate trusts — and the gate keeps a one-line legacy fallback so the decode stays correct regardless of janitor/Django deploy order.
approval-state-vocabulary: the runner writes `APPROVAL_REQUEST_STATES` strings into `agent_tool_approval_request.state`, and the Django side's DRF `choices` and DB `CheckConstraint` derive from the emitted `approval_request_states.generated.json` — one authored home, so a new state can't be rejected by a drifted CHECK at insert time. The freshness oracle welds the checked-in artifact to this constant; moving the live DB constraint still requires a deploy-ordered Django migration (widen before the runner writes a new state), which Django's missing-migration CI check forces whenever this list changes.
session-single-owner: the claim's `SELECT … FOR UPDATE SKIP LOCKED` lock is released when the claim transaction commits — it does NOT protect the session for the duration of the run. Any post-claim write that sets `state = 'queued'` on a `running` row therefore hands the session to a second worker while the first still runs it (two loops interleaving writes on one conversation). Every wake path (ingress `/send`, `/run`-resume, MCP continuation, approval decisions, elevation grants, the janitor's approval-expiry wake) must go through the claim-guarded `requeueForInput` (or `decideElevationRequest`'s equivalent inline CASE), whose WHERE excludes `running` — never a raw `update({state:'queued'})`. The oracle claims a session, fires a wake against it on real PG, and asserts a second `claim` returns nothing.
wake-not-lost-for-completed: the no-op arm of session-single-owner is only safe because `finalizeRun`'s single-statement CAS re-queues a run that COMPLETES with undrained `pending_inputs` — the input appended after the worker's last drain wakes the session instead of stranding on a `completed` row. The rescue applies to EVERY path that would persist `completed`, including the cancel-reopen (a cancelled row finalizing as `completed` with undrained inputs re-queues rather than stranding them on the reopened row), and, via `closeIfIdle`'s equivalent CAS, to the janitor's idle-close. It is still scoped to the `completed` outcome: it is NOT a general "no wakeup is lost" property — see the out-of-scope edges below.
terminal-no-resurrection: `closed` / `cancelled` / `failed` are lifecycle-final (`SESSION_STATE_REAPER`), and chat.ts documents them as 410-terminal, so a wake whose state check read the row BEFORE termination landed must not flip the row back to `queued` afterwards — a raced `/send` against a cancel, a late approval decision, or an elevation grant leaves the appended input inert in `pending_inputs` and the session terminal and unclaimable. The guarantee extends past the wake paths to the worker's own final write and to lookups over terminal rows:

- `finalizeRun` on a `cancelled` row honors ONLY the documented cancel-reopen (outcome `completed` — the runner caught the cancel, persisted the partial reply, reopened). Every other outcome leaves the row `cancelled`: in particular a pod-shutdown suspend (outcome `queued`) that raced the durable cancel used to resurrect the session into the claim pool.
- a late approval decision against a terminal session fails closed instead of half-applying: `applyApprovalDecision` checks the session state before deciding and flips the row `queued → expired` (reusing the existing `expired` state — no vocabulary change) rather than leaving an immortal `approving` row plus an inert decided marker that a later legitimate `allow_restart` restart would drain and dispatch — a stale approved tool call from a dead turn. The narrow check-to-wake race is compensated the same way: `requeueForInput` returns the persisted state, and a wake that reports terminal voids the fresh decision (`approving → expired`); the runner drops any leaked marker because its row is no longer `approving`.
- inert appends on terminal rows still bump `updated_at`, so `findByExternalKey` orders live rows before terminal ones — a dead session can't shadow the live session under the same external key just because a raced append made it look fresher.

The one sanctioned exception is `closed → queued` via `requeueForInput`'s `allowRestartFromClosed`, passed only by triggers whose spec sets `allow_restart` (the session-restart contract, e2e case 3); `cancelled`/`failed` are excluded even then, and `enqueueOrResume`'s external-key resume treats all three as non-resumable (a fresh session is created under the key) so resume can't restart a cancelled session either.

Known, deliberately out-of-scope edges (pre-existing semantics, unchanged by the race fixes — flagged so reviewers don't mistake them for covered):

- reaper presumed-dead overwrite: `reapStuckRunning` re-queues a session whose worker looks dead (stale `claimed_at`). If that worker is actually alive and slow, its eventual `finalizeRun` can overwrite the rescued run's state — the CAS only protects the `queued` window, not two live workers finalizing the same session.
- closed/failed final-write stranding: `finalizeRun` only re-queues undrained inputs when the outcome is `completed`. An input appended mid-run to a session whose run ends `closed`/`failed` strands in `pending_inputs` behind the terminal write. Whether those outcomes should also rescue the input is a semantics question for the team, not silently decided here.
