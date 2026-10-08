import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

// Only paths inside customer analytics are accepted, so a crafted link can't send the back arrow to another site.
export function getConfigurationBackTarget(returnTo: unknown): Breadcrumb | null {
    if (typeof returnTo !== 'string' || !returnTo.startsWith(`${urls.customerAnalytics()}/`)) {
        return null
    }
    const isAccountDetail = returnTo.startsWith(`${urls.customerAnalyticsAccounts()}/`)
    return {
        key: isAccountDetail ? Scene.CustomerAnalyticsAccount : Scene.CustomerAnalytics,
        name: isAccountDetail ? 'Account' : 'Customer analytics',
        path: returnTo,
        iconType: 'cohort',
    }
}
