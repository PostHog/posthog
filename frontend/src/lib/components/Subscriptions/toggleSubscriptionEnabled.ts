import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { subscriptionsPartialUpdate } from '~/generated/core/api'

export async function toggleSubscriptionEnabled(id: number, enabled: boolean): Promise<boolean> {
    try {
        await subscriptionsPartialUpdate(String(getCurrentTeamId()), id, { enabled })
        lemonToast.success(enabled ? 'Subscription enabled' : 'Subscription disabled')
        return true
    } catch (e: any) {
        const detail = typeof e?.detail === 'string' ? e.detail : null
        lemonToast.error(detail ?? 'Could not update subscription')
        return false
    }
}
