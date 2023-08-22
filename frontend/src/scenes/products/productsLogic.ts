import { urls } from 'scenes/urls'
import { Product, ProductKey } from '~/types'

export const products: Product[] = [
    {
        name: 'Product analytics',
        key: ProductKey.PRODUCT_ANALYTICS,
        description: 'Understand your users with trends, funnels, path analysis + more.',
        productUrl: urls.dashboards(),
        productInfoUrl: 'https://posthog.com/product-analytics',
        docsUrl: 'https://posthog.com/product-analytics/documentation',
    },
    {
        name: 'Session replay',
        key: ProductKey.SESSION_REPLAY,
        description:
            'Searchable recordings of people using your app or website with console logs and behavioral bucketing.',
        productUrl: urls.replay(),
        productInfoUrl: 'https://posthog.com/session-replay',
        docsUrl: 'https://posthog.com/session-replay/documentation',
    },
    {
        name: 'Feature flags & A/B testing',
        key: ProductKey.FEATURE_FLAGS,
        description: 'Safely roll out new features and run experiments on changes.',
        productUrl: urls.featureFlags(),
        productInfoUrl: 'https://posthog.com/feature-flags',
        docsUrl: 'https://posthog.com/feature-flags/documentation',
    },
    {
        name: 'Data warehouse',
        key: ProductKey.DATA_WAREHOUSE,
        description: 'Bring your production database, revenue data, CRM contacts or any other data into PostHog.',
        productUrl: urls.dataWarehouse(),
        docsUrl: 'https://posthog.com/docs/data-warehouse',
    },
    {
        name: 'Surveys',
        key: ProductKey.SURVEYS,
        description:
            'Collect qualitative feedback from users, targeting based on page URL, selectors, feature flag, and user properties.',
        productUrl: urls.surveys(),
        docsUrl: 'https://posthog.com/docs/surveys/manual',
    },
]
