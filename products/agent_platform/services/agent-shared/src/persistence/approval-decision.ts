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
 */

import type { ConversationMessage } from '../spec/spec'
import type { ApprovalRequestState, ApprovalStore } from './approval-store'
import type { SessionQueue } from './queue'

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

export type ApplyApprovalDecisionError = 'not_found' | 'not_queued' | 'edits_not_allowed' | 'race_lost'

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
        await deps.queue.update(existing.session_id, { state: 'queued' })
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
    await deps.queue.update(existing.session_id, { state: 'queued' })
    return { ok: true, state: updated.state }
}
