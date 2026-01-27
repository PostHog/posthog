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
        // Single route for now, may want to split in the future
        '/customer_analytics': ['CustomerAnalytics', 'customerAnalytics'],
        '/customer_analytics/configuration': ['CustomerAnalyticsConfiguration', 'customerAnalyticsConfiguration'],
    },
    urls: {
        customerAnalytics: (): string => '/customer_analytics',
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
