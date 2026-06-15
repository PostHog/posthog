/**
 * Internal sentinel used to pass approval decisions from the janitor into a
 * waking runner turn without changing the conversation-message schema.
 *
 * The janitor's `/approvals/:id/decide` endpoint appends a `role: 'user'`
 * message with `text` of the form `<MARKER_PREFIX>:<request_id>` into the
 * session's `pending_inputs`. At turn start the runner scans pending_inputs
 * for these markers BEFORE the usual drain — for each marker it dispatches
 * the approved tool, finalises the approval row, and pushes the synthetic
 * tool_result onto conversation. The marker itself never lands in
 * conversation, so the model never sees the sentinel string.
 *
 * Why a magic string and not a dedicated message kind: v0 ships without a
 * schema migration on pending_inputs. v1 may swap this for a proper
 * internal-only message type once the runner has a settled story for them.
 */

export const APPROVAL_DECIDED_MARKER_PREFIX = '__POSTHOG_APPROVAL_DECIDED__'

/**
 * Build the marker text for a request id. The janitor uses this to compose
 * the synthetic pending_input on approval.
 */
export function buildApprovalDecidedMarker(requestId: string): string {
    return `${APPROVAL_DECIDED_MARKER_PREFIX}:${requestId}`
}

/**
 * Parse a marker text back to its request id, returning null when the
 * message isn't a marker.
 */
export function parseApprovalDecidedMarker(text: string): string | null {
    if (!text.startsWith(`${APPROVAL_DECIDED_MARKER_PREFIX}:`)) {
        return null
    }
    return text.slice(APPROVAL_DECIDED_MARKER_PREFIX.length + 1)
}
