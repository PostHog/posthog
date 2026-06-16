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

import { AssistantMessageRecord } from '../spec/spec'

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
    /** Resolved approver policy at request time — v0 always `["team_admins"]`. */
    approver_scope: { approvers: string[]; allow_edit: boolean; allow_agent_approver: boolean }
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
