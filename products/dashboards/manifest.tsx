import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import type { DashboardsTab } from '../../frontend/src/scenes/dashboard/dashboards/dashboardsLogic'
import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Dashboards',
    urls: {
        dashboards: (tab?: `${DashboardsTab}`): string => (tab ? `/dashboard?tab=${tab}` : '/dashboard'),
        dashboardTemplates: (): string => combineUrl('/dashboard', { templates: '1' }).url,
        dashboard: (id: string | number, highlightInsightId?: string): string =>
            combineUrl(`/dashboard/${id}`, highlightInsightId ? { highlightInsightId } : {}).url,
        dashboardTile: (id: string | number, tileId: string | number): string =>
            `${urls.dashboard(id)}/tiles/${tileId}`,
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
            category: ProductItemCategory.ANALYTICS,
            type: 'dashboard',
            iconType: 'dashboard',
            iconColor: ['var(--color-product-dashboards-light)'],
            href: urls.dashboards(),
            searchKeywords: ['boards', 'charts'],
            searchTabs: [
                { name: 'My dashboards', href: urls.dashboards('yours') },
                {
                    name: 'Cross-project dashboards',
                    href: urls.dashboards('cross-project'),
                    flag: FEATURE_FLAGS.CROSS_PROJECT_DASHBOARDS,
                },
            ],
            sceneKey: 'Dashboards',
            sceneKeys: ['Dashboard', 'Dashboards'],
        },
    ],
}
