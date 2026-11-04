import { urls } from 'scenes/urls'

import type { AccountViewApi } from '../../generated/api.schemas'
import { parseAccountViewContent } from '../../scenes/CustomerAnalyticsAccountScene/accountViewDocument'
import { getDotMatrixTileSource } from './dotMatrixTileConfig'

// Pinned: book links use this query value to request the account setup prompt.
export const PRODUCT_ACTIVITY_SETUP = 'product-activity'

export function getAccountProductActivityUrl(accountId: string, views: AccountViewApi[] = []): string {
    const view = views.find((candidate) =>
        parseAccountViewContent(candidate.content).some(
            (component) =>
                component.kind === 'dot_matrix' &&
                getDotMatrixTileSource(component.config?.source)?.kind === 'product_usage'
        )
    )
    return view
        ? urls.customerAnalyticsAccount(accountId, `view:${view.id}`)
        : `${urls.customerAnalyticsAccount(accountId)}?setup=${PRODUCT_ACTIVITY_SETUP}`
}
