import { urls } from 'scenes/urls'

import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Churn prediction',
    scenes: {
        ChurnPrediction: {
            name: 'Churn prediction',
            import: () => import('./frontend/ChurnPredictionScene'),
            projectBased: true,
            defaultDocsPath: '/docs/web-analytics/churn-prediction',
            activityScope: 'ChurnPrediction',
        },
    },
    routes: {
        '/churn-prediction': ['ChurnPrediction', 'churnPrediction'],
    },
    urls: {
        churnPrediction: (): string => '/churn-prediction',
    },
    treeItemsProducts: [
        {
            path: 'Churn prediction',
            iconType: 'warning',
            href: urls.churnPrediction(),
        },
        {
            path: 'Churn settings',
            iconType: 'settings',
            href: urls.churnPrediction(),
        },
    ],
}
