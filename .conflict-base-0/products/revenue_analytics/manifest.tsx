import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Revenue Analytics',
    scenes: {
        RevenueAnalytics: {
            name: 'Revenue Analytics',
            import: () => import('./frontend/RevenueAnalyticsScene'),
            projectBased: true,
            defaultDocsPath: '/docs/revenue-analytics',
            activityScope: 'RevenueAnalytics',
        },
    },
    routes: {
        '/revenue_analytics': ['RevenueAnalytics', 'revenueAnalytics'],
    },
    urls: {
        revenueAnalytics: (): string => '/revenue_analytics',
    },
    treeItemsProducts: [
        {
            path: 'Revenue analytics',
            category: 'Analytics',
            href: urls.revenueAnalytics(),
            type: 'revenue',
            tags: ['beta'],
            flag: FEATURE_FLAGS.REVENUE_ANALYTICS,
        },
    ],
    fileSystemTypes: {
        revenue: {
            name: 'Revenue',
            iconType: 'revenue_analytics' as FileSystemIconType,
            href: () => urls.revenueAnalytics(),
            iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
            filterKey: 'revenue',
        },
    },
    treeItemsMetadata: [
        {
            path: 'Revenue settings',
            category: 'Definitions',
            iconType: 'revenue_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
            href: urls.revenueSettings(),
            flag: FEATURE_FLAGS.REVENUE_ANALYTICS,
        },
        {
            path: 'Marketing settings',
            category: 'Definitions',
            iconType: 'revenue_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
            href: urls.marketingAnalytics(),
            flag: FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
        },
    ],
}
