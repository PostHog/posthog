import { dashboard, type InsightDefinition, text, type TileLayout } from '@posthog/sdk/define'

import { tags } from '../shared/teams'
import { exportResults } from './exports'
import {
    alertCreation,
    alertFailuresByExceptionTypeAggregated,
    apiCallsOriginatingFromOurTerraformProvider,
    createdSubscriptions,
    dashboardCreatedUniqueUsersByEventSSource,
    dashboardsCreatedFromTemplateUniqueUsers,
    sharedDashboardStats,
    usageByRole,
} from './insights'
import { subscriptionDelivery } from './subscriptions'

// The layout ids are the dashboard's own tile ids, from when the tiles were placed in the UI.
function at(i: string, x: number, y: number, w: number, h: number): { sm: TileLayout } {
    return { sm: { h, i, w, x, y, minH: 1, minW: 1, moved: false, static: false } }
}

const show = (
    insight: InsightDefinition,
    layouts: { sm: TileLayout },
    color?: string
): { insight: InsightDefinition; layouts: { sm: TileLayout }; color?: string } => ({
    insight,
    layouts,
    ...(color ? { color } : {}),
})

export const keyMetrics = dashboard('team_analytics_platform_key_metrics', {
    name: '[team-analytics-platform] Key metrics',
    pinned: true,
    tags: [tags.managed],
    tiles: [
        show(sharedDashboardStats, at('4386313', 0, 0, 4, 5)),
        show(alertCreation, at('4386146', 4, 0, 4, 5)),
        show(createdSubscriptions, at('4386493', 8, 0, 4, 5), 'white'),
        show(dashboardsCreatedFromTemplateUniqueUsers, at('4385815', 0, 5, 6, 5)),
        show(dashboardCreatedUniqueUsersByEventSSource, at('6241075', 6, 5, 6, 5)),
        text('## Alerts, subscriptions & exports 🚨', { layouts: at('6274566', 0, 10, 12, 1) }),
        show(exportResults.us, at('4385817', 0, 11, 6, 5)),
        show(exportResults.eu, at('4704520', 6, 11, 6, 5)),
        show(subscriptionDelivery.US, at('subscription_us', 0, 16, 6, 5)),
        show(subscriptionDelivery.EU, at('subscription_eu', 6, 16, 6, 5)),
        show(alertFailuresByExceptionTypeAggregated, at('6157400', 0, 21, 12, 5)),
        text('## Terraform 🛠️', { layouts: at('6274570', 0, 26, 12, 1) }),
        show(apiCallsOriginatingFromOurTerraformProvider, at('4788951', 0, 27, 12, 3)),
        show(usageByRole, at('3202514', 0, 30, 12, 5)),
    ],
})
