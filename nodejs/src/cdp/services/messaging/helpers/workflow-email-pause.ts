import { HogFunctionType } from '~/cdp/types'

/**
 * Whether this workflow's email is paused, and the customer-facing reason.
 *
 * Stamped into the synthetic hog function's metadata by HogFlowFunctionsService, which is the only
 * flow-level state in scope here. The `HogFlow` post_save signal publishes a worker config reload
 * when the pause is written, so an in-flight run and an already-queued batch send both stop at the
 * email worker's choke point instead of only newly started runs.
 */
export function parseWorkflowEmailPause(
    metadata: HogFunctionType['metadata']
): { reason: string; byStaff: boolean } | null {
    if (!metadata?.email_sending_paused_at) {
        return null
    }
    const reason = metadata.email_sending_paused_reason
    return {
        reason: typeof reason === 'string' ? reason : '',
        byStaff: metadata.email_sending_paused_by === 'staff',
    }
}
