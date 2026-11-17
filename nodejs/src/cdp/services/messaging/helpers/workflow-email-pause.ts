import { HogFunctionType } from '~/cdp/types'

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
