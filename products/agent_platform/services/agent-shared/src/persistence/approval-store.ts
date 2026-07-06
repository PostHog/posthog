/**
 * Approval-gated tool requests — interface + in-memory test impl.
 *
 * The dispatcher writes a row when an approval-gated tool call is intercepted.
 * Sessions do NOT park — the model receives a synthetic queued tool_result
 * containing an approval link. The approval API later marks the row
 * `approving` → `dispatched` (running the real tool platform-side) and
 * injects the result back into the session.
 *
 * Idempotency: a new row for the same `(session_id, tool_name, args_hash)`
 * with `state='queued'` returns the existing row instead of inserting a
 * duplicate. After a terminal state (rejected / expired / dispatched*) the
 * model can re-issue the call and the dispatcher creates a fresh row.
 */

import { createHash } from 'node:crypto'

import { ApprovalType, AssistantMessageRecord } from '../spec/spec'

export type ApprovalRequestState = 'queued' | 'approving' | 'dispatched' | 'dispatched_failed' | 'rejected' | 'expired'

export interface ApprovalRequest {
    id: string
    session_id: string
    application_id: string
    team_id: number
    revision_id: string
    turn: number
    tool_call_id: string
    tool_name: string
    proposed_args: Record<string, unknown>
    args_hash: Buffer
    /** Snapshot of the assistant message that emitted the call. */
    assistant_message: AssistantMessageRecord
    /**
     * Resolved approval policy at request time. `type` decides who may clear it:
     * `principal` (the session principal, via the ingress decision API) or
     * `agent` (the agent's owners, via the console). `allow_edit` gates
     * approver-edited args.
     */
    approver_scope: { type: ApprovalType; allow_edit: boolean }
    state: ApprovalRequestState
    decision_by: string | null
    decision_at: string | null
    decision_reason: string | null
    decided_args: Record<string, unknown> | null
    /** Set on terminal decision. `{result?, error?}`. */
    dispatch_outcome: { result?: unknown; error?: string } | null
    created_at: string
    expires_at: string
}

/**
 * Effective approval authority for a stored row. New rows carry `type`; rows
 * queued before the principal/agent rebuild carry the legacy `approvers[]`
 * scope with no `type`, so `scope.type` is `undefined` on them. Map a legacy
 * `team_admins` scope → `agent` so an in-flight old row stays gated to the
 * console (and isn't mistaken for a principal request) for its whole TTL during
 * the migration window. Mirrors the Django `approvals_decide` fallback — every
 * surface that gates on type MUST resolve through this, not read `.type` raw.
 */
export function effectiveApprovalType(scope: ApprovalRequest['approver_scope']): ApprovalType {
    const s = scope as unknown as { type?: unknown; approvers?: unknown }
    if (s.type === 'agent' || s.type === 'principal') {
        return s.type
    }
    if (Array.isArray(s.approvers) && s.approvers.includes('team_admins')) {
        return 'agent'
    }
    return 'principal'
}

/**
 * Wire shape for an approval row — matches the Django `approvals` serializer and
 * the frontend `AgentApprovalRequest`. Drops the internal `args_hash` (a Buffer)
 * and reports a concrete `approver_scope.type`.
 */
export interface SerializedApprovalRequest {
    id: string
    session_id: string
    application_id: string
    team_id: number
    revision_id: string
    turn: number
    tool_call_id: string
    tool_name: string
    proposed_args: Record<string, unknown>
    decided_args: Record<string, unknown> | null
    assistant_message: AssistantMessageRecord
    approver_scope: { type: ApprovalType; allow_edit: boolean }
    state: ApprovalRequestState
    decision_by: string | null
    decision_at: string | null
    decision_reason: string | null
    dispatch_outcome: { result?: unknown; error?: string } | null
    created_at: string
    expires_at: string
}

/**
 * Serialize a stored row to the wire shape clients consume. Shared by the
 * ingress read route (`GET /approvals/:id`) and the runner's `approval_required`
 * SSE frame so every surface emits an identical shape. Resolves
 * `approver_scope.type` through `effectiveApprovalType` so legacy rows report a
 * concrete type instead of `undefined`.
 */
export function serializeApprovalRequest(row: ApprovalRequest): SerializedApprovalRequest {
    return {
        id: row.id,
        session_id: row.session_id,
        application_id: row.application_id,
        team_id: row.team_id,
        revision_id: row.revision_id,
        turn: row.turn,
        tool_call_id: row.tool_call_id,
        tool_name: row.tool_name,
        proposed_args: row.proposed_args,
        decided_args: row.decided_args,
        assistant_message: row.assistant_message,
        approver_scope: { type: effectiveApprovalType(row.approver_scope), allow_edit: row.approver_scope.allow_edit },
        state: row.state,
        decision_by: row.decision_by,
        decision_at: row.decision_at,
        decision_reason: row.decision_reason,
        dispatch_outcome: row.dispatch_outcome,
        created_at: row.created_at,
        expires_at: row.expires_at,
    }
}

export interface UpsertApprovalRequestInput {
    id: string
    session_id: string
    application_id: string
    team_id: number
    revision_id: string
    turn: number
    tool_call_id: string
    tool_name: string
    proposed_args: Record<string, unknown>
    assistant_message: AssistantMessageRecord
    approver_scope: ApprovalRequest['approver_scope']
    expires_at: string
}

export interface UpsertApprovalRequestResult {
    request: ApprovalRequest
    /** True when an existing queued row was returned instead of inserting a new one. */
    deduped: boolean
}

export interface DecideApprovalInput {
    decided_by: string
    decided_at: string
    /** Approver's free-form reason, surfaces in the synthetic tool_result. */
    reason?: string
    /** Approver-edited args. Caller must validate `allow_edit` in spec policy. */
    decided_args?: Record<string, unknown>
}

export interface ListApprovalsOpts {
    state?: ApprovalRequestState | ApprovalRequestState[]
    /**
     * Narrow a team-scoped list to a single application. Ignored by
     * `listByApplication` / `listBySession` (which already key on a more
     * specific id).
     */
    applicationId?: string
    limit?: number
    offset?: number
}

export interface ApprovalStore {
    /**
     * UPSERT by (session_id, tool_name, args_hash) WHERE state='queued'.
     * Returns the existing queued row if one exists, else inserts the new row.
     */
    upsertQueued(input: UpsertApprovalRequestInput): Promise<UpsertApprovalRequestResult>
    get(id: string): Promise<ApprovalRequest | null>
    /**
     * Tenant-scoped variant of `get` for request-path callers: only returns the
     * row when it belongs to `applicationId`. Use this from HTTP handlers that
     * receive a caller-supplied id so a leaked id can't resolve another tenant's
     * request; keep `get` for trusted internal callers (runner, sweep).
     */
    getForApplication(id: string, applicationId: string): Promise<ApprovalRequest | null>
    /** Returns the most recently created request for a (session, tool, args). */
    findLatestByArgs(sessionId: string, toolName: string, argsHash: Buffer): Promise<ApprovalRequest | null>
    /** Atomically flip `queued` → `approving` with stamp. Returns null when not in `queued`. */
    markApproving(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null>
    /** Final state after the platform ran the tool. */
    markDispatched(id: string, outcome: { result?: unknown; error?: string }): Promise<ApprovalRequest | null>
    markRejected(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null>
    /** Janitor sweep — flips `queued` rows past `expires_at` to `expired`. Returns rows that flipped. */
    expireQueued(now: string): Promise<ApprovalRequest[]>
    /** UI / inbox listings. team_id and application_id are denormalised for these. */
    listByTeam(teamId: number, opts?: ListApprovalsOpts): Promise<ApprovalRequest[]>
    listByApplication(applicationId: string, opts?: ListApprovalsOpts): Promise<ApprovalRequest[]>
    listBySession(sessionId: string, opts?: ListApprovalsOpts): Promise<ApprovalRequest[]>
    /** Count `queued` rows for a team — drives the fleet-stats badge. */
    countQueuedByTeam(teamId: number): Promise<number>
    /** Count `queued` rows for one application — drives the per-agent badge. */
    countQueuedByApplication(applicationId: string): Promise<number>
}

/**
 * Canonicalise a JSON-serialisable args object so semantically identical
 * args produce the same SHA-256. Recursive key sort + JSON.stringify + sha256.
 *
 * Numbers / booleans / strings / arrays / null pass through unchanged.
 * Floats vs ints (`1` vs `1.0`) are NOT normalised — see plan §5.1.
 */
export function hashCanonicalArgs(args: unknown): Buffer {
    const canonical = JSON.stringify(sortKeys(args))
    return createHash('sha256').update(canonical, 'utf8').digest()
}

function sortKeys(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value && typeof value === 'object') {
        const out: Record<string, unknown> = {}
        for (const k of Object.keys(value as Record<string, unknown>).sort()) {
            out[k] = sortKeys((value as Record<string, unknown>)[k])
        }
        return out
    }
    return value
}
