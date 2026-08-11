import api from 'lib/api'
import { urls } from 'scenes/urls'
import type { ApplyOp } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

/** Perform an op the browser owns, returning whether it handled it.
 *
 * Lives in the view rather than in `setupPlanLogic`: these need the router and the
 * scene's own logics, and importing those into the plan logic drags the whole scene
 * dependency graph — sourceManagementLogic and friends — into everything that touches
 * a suggestion. The plan logic changes config; the view moves the user.
 *
 * Anything that leaves the product opens in a new tab. The user is midway through a
 * setup checklist, and navigating away to authorise an ad platform loses their place
 * in it.
 *
 * Handles exactly the ops in the backend's `NAVIGATE_OPS`. `fix_platform_urls` is not
 * here on purpose: it is advice about an ad platform's tracking template, so the row
 * renders it rather than navigating anywhere. Anything unrecognised returns false and
 * the caller leaves the row alone.
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
