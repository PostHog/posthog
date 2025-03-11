import { combineUrl } from 'kea-router'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Dashboards',
    urls: {
        dashboards: (): string => '/dashboard',
        dashboard: (id: string | number, highlightInsightId?: string): string =>
            combineUrl(`/dashboard/${id}`, highlightInsightId ? { highlightInsightId } : {}).url,
        dashboardTextTile: (id: string | number, textTileId: string | number): string =>
            `${urls.dashboard(id)}/text-tiles/${textTileId}`,
        dashboardSharing: (id: string | number): string => `/dashboard/${id}/sharing`,
        dashboardSubcriptions: (id: string | number): string => `/dashboard/${id}/subscriptions`,
        dashboardSubcription: (id: string | number, subscriptionId: string): string =>
            `/dashboard/${id}/subscriptions/${subscriptionId}`,

        sharedDashboard: (shareToken: string): string => `/shared_dashboard/${shareToken}`,
    },
}
