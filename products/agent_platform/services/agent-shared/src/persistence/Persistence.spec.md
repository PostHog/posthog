# Persistence

Postgres-backed stores for the agent runtime, including the approval-gated tool-call store. Approval authority (who may clear a gated call) and the wire shape the console/ingress consume are resolved here through a single owner.

## invariants

- approval-authority-totality
- approval-wire-resolved
- approval-state-vocabulary

## works when

- typechecks
- boundary "approval-authority-totality" at effectiveApprovalType via test "approval-authority totality"
- boundary "approval-wire-resolved" at serializeApprovalRequest
- passes test "resolves a legacy approvers"
- boundary "approval-state-vocabulary" at APPROVAL_REQUEST_STATES via test "spec generated artifacts"

## why

approval-authority-totality: `effectiveApprovalType` decides WHO may clear a gated tool call — `principal` (the end user, weaker gate) or `agent` (the owner via console, stronger gate). Recognition of a concrete authority is derived from `ApprovalTypeSchema` (not a hardcoded `=== 'agent' || === 'principal'`), so a new authority added to the enum is honored instead of silently downgrading to the weakest gate. The oracle enumerates `ApprovalTypeSchema.options` — the same source that defines the vocabulary — and asserts each round-trips, with a floor so it can't pass vacuously if the projection collapses.
approval-wire-resolved: every surface that gates on approval authority (janitor read routes, the runner's `approval_required` SSE frame, the ingress decision API) must consume a resolved `approver_scope.type`, never the raw legacy `approvers[]` shape. `serializeApprovalRequest` is the single serializer that resolves it via `effectiveApprovalType`; a hand-rolled copy that returned the scope raw had drifted and left legacy rows with an undefined type. The oracle asserts a legacy scope is resolved (not passed raw), which is the contract the Django decide gate trusts — and the gate keeps a one-line legacy fallback so the decode stays correct regardless of janitor/Django deploy order.
approval-state-vocabulary: the runner writes `APPROVAL_REQUEST_STATES` strings into `agent_tool_approval_request.state`, and the Django side's DRF `choices` and DB `CheckConstraint` derive from the emitted `approval_request_states.generated.json` — one authored home, so a new state can't be rejected by a drifted CHECK at insert time. The freshness oracle welds the checked-in artifact to this constant; moving the live DB constraint still requires a deploy-ordered Django migration (widen before the runner writes a new state), which Django's missing-migration CI check forces whenever this list changes.
