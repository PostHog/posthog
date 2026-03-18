import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Dashboards',
    urls: {
        dashboards: (): string => '/dashboard',
        dashboard: (id: string | number, highlightInsightId?: string): string =>
            combineUrl(`/dashboard/${id}`, highlightInsightId ? { highlightInsightId } : {}).url,
        dashboardTextTile: (id: string | number, textTileId: string | number): string =>
            `${urls.dashboard(id)}/text-tiles/${textTileId}`,
        dashboardSharing: (id: string | number): string => `/dashboard/${id}/sharing`,
        dashboardSubscriptions: (id: string | number): string => `/dashboard/${id}/subscriptions`,
        dashboardSubscription: (id: string | number, subscriptionId: string): string =>
            `/dashboard/${id}/subscriptions/${subscriptionId}`,

        sharedDashboard: (shareToken: string): string => `/shared_dashboard/${shareToken}`,
    },
    fileSystemTypes: {
        dashboard: {
            name: 'Dashboard',
            iconType: 'dashboard' as FileSystemIconType,
            href: (ref: string) => urls.dashboard(ref),
            iconColor: ['var(--color-product-dashboards-light)'],
            filterKey: 'dashboard',
        },
    },
    treeItemsNew: [
        {
            path: `Dashboard`,
            type: 'dashboard',
            href: urls.dashboards() + '#newDashboard=modal',
            iconType: 'dashboard' as FileSystemIconType,
            iconColor: ['var(--color-product-dashboards-light)'] as FileSystemIconColor,
            sceneKey: 'Dashboard',
            sceneKeys: ['Dashboards', 'Dashboard'],
        },
    ],
    treeItemsProducts: [
        {
            path: 'Dashboards',
            intents: [ProductKey.PRODUCT_ANALYTICS],
            category: 'Analytics',
            type: 'dashboard',
            iconType: 'dashboard',
            iconColor: ['var(--color-product-dashboards-light)'],
            href: urls.dashboards(),
            sceneKey: 'Dashboards',
            sceneKeys: ['Dashboard', 'Dashboards'],
        },
    ],
}
