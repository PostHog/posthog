/**
 * Shared "decide a queued approval + wake its session" logic, so every decision
 * surface drives the same transition without one depending on another:
 *   - the ingress principal-decision API (a Slack button / client tool / the
 *     PostHog Code card — the session principal clears their own gate),
 *   - the janitor's `/approvals/:id/decide` RPC (Django forwards `agent`/owner
 *     decisions here),
 *   - the janitor expiry sweep (a timed-out queue, via `markRejected`/expire).
 *
 * Each caller authorises WHO may decide; this just executes the decision against
 * the approval store + session queue. The approval row's atomic `queued →
 * approving` flip is the single-use guard — a replayed decision loses the race.
 *
 * The runner picks up the decision on its next turn: an approve appends an
 * `APPROVAL_DECIDED_MARKER` into `pending_inputs` (the runner dispatches the
 * real tool, finalises the row, and pushes the synthetic tool_result); a reject
 * materialises the rejection envelope straight into `pending_inputs`.
 *
 * A decision against a session that already terminated fails closed: the row
 * is expired (never left `approving`) and no marker is appended, so a later
 * `allow_restart` restart can't drain a stale approved call from a dead turn.
 */

import type { ConversationMessage } from '../spec/spec'
import type { ApprovalRequestState, ApprovalStore } from './approval-store'
import type { SessionQueue } from './queue'
import { isFinalSessionState } from './session-state-reaper'

/**
 * Sentinel passed from a decision surface into a waking runner turn without a
 * `pending_inputs` schema change. The runner scans for it BEFORE the usual
 * drain; the marker itself never lands in `conversation`, so the model never
 * sees the sentinel string. v1 may swap this for a dedicated message kind.
 */
export const APPROVAL_DECIDED_MARKER_PREFIX = '__POSTHOG_APPROVAL_DECIDED__'

export function buildApprovalDecidedMarker(requestId: string): string {
    return `${APPROVAL_DECIDED_MARKER_PREFIX}:${requestId}`
}

/** Parse a marker text back to its request id, or null when it isn't a marker. */
export function parseApprovalDecidedMarker(text: string): string | null {
    if (!text.startsWith(`${APPROVAL_DECIDED_MARKER_PREFIX}:`)) {
        return null
    }
    return text.slice(APPROVAL_DECIDED_MARKER_PREFIX.length + 1)
}

export type ApprovalDecision = 'approve' | 'reject'

export interface ApplyApprovalDecisionInput {
    requestId: string
    /**
     * Tenant scope — when set, the row must belong to this application (a
     * leaked-id guard). Edge callers (ingress, Django→janitor) always pass it;
     * a trusted internal caller may omit it for an unscoped lookup.
     */
    applicationId?: string
    decision: ApprovalDecision
    /** Identifier of whoever decided (posthog uuid / slack user id / jwt sub). */
    decidedBy: string
    /** Approver's free-form reason; surfaces in the synthetic result. */
    reason?: string
    /** Approver-edited args. Only honoured when the policy set `allow_edit`. */
    editedArgs?: Record<string, unknown>
}

export type ApplyApprovalDecisionError =
    | 'not_found'
    | 'not_queued'
    | 'edits_not_allowed'
    | 'race_lost'
    /** The row's session already terminated — the approval was expired instead. */
    | 'session_terminal'

export type ApplyApprovalDecisionResult =
    | { ok: true; state: ApprovalRequestState }
    | { ok: false; error: ApplyApprovalDecisionError; state?: ApprovalRequestState }

/**
 * Decide a queued approval and wake its session. Authorisation is the caller's
 * job — this only executes the decision. Returns a discriminated result the
 * caller maps to its transport (HTTP status, Slack reply, …).
 */
export async function applyApprovalDecision(
    deps: { approvals: ApprovalStore; queue: SessionQueue },
    input: ApplyApprovalDecisionInput,
    now: () => number = Date.now
): Promise<ApplyApprovalDecisionResult> {
    const existing = input.applicationId
        ? await deps.approvals.getForApplication(input.requestId, input.applicationId)
        : await deps.approvals.get(input.requestId)
    if (!existing) {
        return { ok: false, error: 'not_found' }
    }
    if (existing.state !== 'queued') {
        return { ok: false, error: 'not_queued', state: existing.state }
    }
    // edited_args is only honoured when the policy opted in. Surface a
    // structured error so the caller can map it to a user-facing message
    // rather than silently dropping the edits.
    if (input.editedArgs !== undefined && !existing.approver_scope.allow_edit) {
        return { ok: false, error: 'edits_not_allowed' }
    }
    // Fail closed on a dead session. Deciding an approval whose session
    // already terminated must not leave an immortal 'approving' row plus an
    // inert decided marker in pending_inputs — a later legitimate
    // allow_restart restart would drain that marker and dispatch a stale
    // approved tool call from a dead turn. The row flips to 'expired' (the
    // existing "can no longer be decided" state) and nothing is appended.
    const session = await deps.queue.get(existing.session_id)
    if (!session || isFinalSessionState(session.state)) {
        const expired = await deps.approvals.markExpired(existing.id)
        if (!expired) {
            return { ok: false, error: 'race_lost' }
        }
        return { ok: false, error: 'session_terminal', state: expired.state }
    }

    const decidedAt = new Date(now()).toISOString()
    if (input.decision === 'approve') {
        const updated = await deps.approvals.markApproving(input.requestId, {
            decided_by: input.decidedBy,
            decided_at: decidedAt,
            reason: input.reason,
            decided_args: input.editedArgs,
        })
        if (!updated) {
            return { ok: false, error: 'race_lost' }
        }
        const wake: ConversationMessage = {
            role: 'user',
            content: [{ type: 'text', text: buildApprovalDecidedMarker(updated.id) }],
            timestamp: now(),
        }
        await deps.queue.appendPendingInput(existing.session_id, wake)
        // Guarded wake, never a raw state write: a running session keeps its
        // owner (the live worker drains the marker), and a session that
        // terminated after the approval queued (cancel, idle-close, failure)
        // is not resurrected by a late decision.
        const woken = await deps.queue.requeueForInput(existing.session_id)
        if (woken == null || isFinalSessionState(woken)) {
            // The session terminated between the state check above and the
            // wake — the marker already landed, but expiring the row de-fangs
            // it: the runner drops markers whose row isn't 'approving', so a
            // later allow_restart restart can't dispatch this call.
            await deps.approvals.markExpired(updated.id)
            return { ok: false, error: 'session_terminal', state: 'expired' }
        }
        return { ok: true, state: updated.state }
    }

    // reject: terminal here. Materialise the synthetic rejection straight into
    // pending_inputs as a `user` message (not a tool_result — strict providers
    // 400 when a tool_result follows the closing assistant message).
    const updated = await deps.approvals.markRejected(input.requestId, {
        decided_by: input.decidedBy,
        decided_at: decidedAt,
        reason: input.reason,
    })
    if (!updated) {
        return { ok: false, error: 'race_lost' }
    }
    const rejected: ConversationMessage = {
        role: 'user',
        content: [
            {
                type: 'text',
                text: JSON.stringify({
                    approval: {
                        request_id: updated.id,
                        state: 'rejected',
                        decided_by: updated.decision_by ?? undefined,
                        reason: updated.decision_reason ?? undefined,
                    },
                }),
            },
        ],
        timestamp: now(),
    }
    await deps.queue.appendPendingInput(existing.session_id, rejected)
    // Same guarded wake as the approve arm. No terminal compensation here:
    // the row is already terminal ('rejected' — the tool can never dispatch),
    // and the envelope is plain prose a restarted session may harmlessly read.
    await deps.queue.requeueForInput(existing.session_id)
    return { ok: true, state: updated.state }
}
