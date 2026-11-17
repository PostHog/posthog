import { HogFunctionType } from '~/cdp/types'

// HogFlowFunctionsService stamps the pause into the synthetic hog function's metadata. The `HogFlow` post_save
// signal reloads worker config when the pause is written, so in-flight runs and queued sends stop too.
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
