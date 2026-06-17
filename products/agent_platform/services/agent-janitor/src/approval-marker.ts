/**
 * Janitor mirror of the runner's approval-marker contract. Kept in sync
 * with `services/agent-runner/src/loop/approval-marker.ts` so a decided
 * approval can wake a sleeping session and the runner can recognise the
 * marker on its next turn.
 *
 * The janitor never parses markers — it only writes them. Keeping the
 * builder local (rather than importing from agent-runner) avoids a
 * cross-service dependency for what is effectively a serialisation
 * format. If this drifts, the runner drops the marker as stale and
 * logs a warning; failures fail noisily.
 */

export const APPROVAL_DECIDED_MARKER_PREFIX = '__POSTHOG_APPROVAL_DECIDED__'

export function buildApprovalDecidedMarker(requestId: string): string {
    return `${APPROVAL_DECIDED_MARKER_PREFIX}:${requestId}`
}
