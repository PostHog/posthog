import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Customer analytics',
    scenes: {
        CustomerAnalytics: {
            import: () => import('./frontend/CustomerAnalyticsScene'),
            defaultDocsPath: '/docs/customer-analytics',
            projectBased: true,
            name: 'Customer analytics',
            description: 'Understand how your customers interact with your product ',
            iconType: 'cohort',
        },
        CustomerAnalyticsConfiguration: {
            import: () =>
                import('./frontend/scenes/CustomerAnalyticsConfigurationScene/CustomerAnalyticsConfigurationScene'),
            defaultDocsPath: '/docs/customer-analytics/configure-your-dashboard',
            projectBased: true,
            name: 'Customer analytics configuration',
        },
    },
    routes: {
        '/customer_analytics/dashboard': ['CustomerAnalytics', 'customerAnalyticsDashboard'],
        '/customer_analytics/journeys': ['CustomerAnalytics', 'customerAnalyticsJourneys'],
        '/customer_analytics/configuration': ['CustomerAnalyticsConfiguration', 'customerAnalyticsConfiguration'],
    },
    redirects: {
        '/customer_analytics': (_params, searchParams, hashParams) =>
            combineUrl('/customer_analytics/dashboard', searchParams, hashParams).url,
    },
    urls: {
        customerAnalytics: (): string => '/customer_analytics',
        customerAnalyticsDashboard: (): string => '/customer_analytics/dashboard',
        customerAnalyticsJourneys: (): string => '/customer_analytics/journeys',
        customerAnalyticsConfiguration: (): string => '/customer_analytics/configuration',
    },
    treeItemsProducts: [
        {
            path: 'Customer analytics',
            intents: [ProductKey.CUSTOMER_ANALYTICS],
            category: 'Analytics',
            iconType: 'cohort',
            href: urls.customerAnalytics(),
            tags: ['beta'],
            flag: FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            sceneKey: 'CustomerAnalytics',
        },
    ],
}
