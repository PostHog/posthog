import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Customer analytics',
    scenes: {
        CustomerAnalytics: {
            import: () => import('./frontend/CustomerAnalyticsScene'),
            projectBased: true,
            name: 'Customer analytics',
            description: 'Understand how your customers interact with your product ',
            iconType: 'cohort',
        },
    },
    routes: {
        // Single route for now, may want to split in the future
        '/customer_analytics': ['CustomerAnalytics', 'customerAnalytics'],
    },
    urls: {
        customerAnalytics: (): string => '/customer_analytics',
    },
    treeItemsProducts: [
        {
            path: 'Customer analytics',
            intents: [ProductKey.CUSTOMER_ANALYTICS],
            category: 'Unreleased',
            iconType: 'cohort',
            href: urls.customerAnalytics(),
            tags: ['alpha'],
            flag: FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            sceneKey: 'CustomerAnalytics',
        },
    ],
}
