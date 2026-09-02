import api from 'lib/api'
import { urls } from 'scenes/urls'
import type { ApplyOp } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

/** Perform an op the browser owns, returning whether it handled it.
 *
 * In the view rather than `setupPlanLogic` to keep the scene's dependency graph —
 * sourceManagementLogic and friends — out of everything that touches a suggestion.
 *
 * New tabs throughout: the user is midway through a checklist and navigating away
 * loses their place in it.
 */
export function runNavigateOp(op: ApplyOp): boolean {
    switch (op.op) {
        case 'open_oauth':
            window.open(
                api.integrations.authorizeUrl({
                    kind: op.kind as string,
                    next: window.location.pathname + window.location.search,
                }),
                '_blank',
                'noopener'
            )
            return true
        case 'open_source_wizard':
            window.open(
                urls.dataWarehouseSourceNew(op.kind as string, urls.marketingAnalyticsApp(), 'Marketing analytics'),
                '_blank',
                'noopener'
            )
            return true
        case 'open_settings':
            window.open(urls.settings(op.anchor as any, 'marketing-settings'), '_blank', 'noopener')
            return true
        default:
            return false
    }
}
