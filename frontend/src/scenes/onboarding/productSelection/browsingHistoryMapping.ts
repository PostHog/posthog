import { ProductKey, WebsiteBrowsingHistoryProdInterest } from '~/queries/schema/schema-general'

import { availableOnboardingProducts } from '../utils'

// Mapping from WebsiteBrowsingHistoryProdInterest to ProductKey - single source of truth for product mapping
// null = no onboarding product yet
const PROD_INTEREST_TO_PRODUCT: Record<WebsiteBrowsingHistoryProdInterest, ProductKey | null> = {
    'product-analytics': ProductKey.PRODUCT_ANALYTICS,
    'web-analytics': ProductKey.WEB_ANALYTICS,
    'session-replay': ProductKey.SESSION_REPLAY,
    'feature-flags': ProductKey.FEATURE_FLAGS,
    experiments: ProductKey.EXPERIMENTS,
    'error-tracking': ProductKey.ERROR_TRACKING,
    surveys: ProductKey.SURVEYS,
    'data-warehouse': ProductKey.DATA_WAREHOUSE,
    'llm-analytics': ProductKey.LLM_ANALYTICS,
    'revenue-analytics': null,
    workflows: null,
    logs: null,
    endpoints: null,
}

// Human-readable labels for display
const PROD_INTEREST_LABELS: Record<WebsiteBrowsingHistoryProdInterest, string> = {
    'product-analytics': 'Product analytics',
    'web-analytics': 'Web analytics',
    'session-replay': 'Session replay',
    'feature-flags': 'Feature flags',
    experiments: 'Experiments',
    'error-tracking': 'Error tracking',
    surveys: 'Surveys',
    'data-warehouse': 'Data warehouse',
    'llm-analytics': 'LLM analytics',
    'revenue-analytics': 'Revenue analytics',
    workflows: 'Workflows',
    logs: 'Logs',
    endpoints: 'Endpoints',
}

/**
 * Maps browsing history items to ProductKey values.
 * Only returns products that are available in onboarding.
 */
export function mapBrowsingHistoryToProducts(browsingHistory: string[]): ProductKey[] {
    const products = browsingHistory
        .map((page) => PROD_INTEREST_TO_PRODUCT[page as WebsiteBrowsingHistoryProdInterest])
        .filter((key): key is ProductKey => key !== null && key in availableOnboardingProducts)

    return [...new Set(products)]
}

/**
 * Maps AI product keys (hyphenated format from WebsiteBrowsingHistoryProdInterest) to ProductKey values.
 * Only returns products that are available in onboarding.
 */
export function mapAIProductsToProductKeys(products: string[]): ProductKey[] {
    return products
        .map((p) => PROD_INTEREST_TO_PRODUCT[p as WebsiteBrowsingHistoryProdInterest])
        .filter((key): key is ProductKey => key !== null && key in availableOnboardingProducts)
}

/** Gets human-readable labels for browsing history items. */
export function getBrowsingHistoryLabels(browsingHistory: string[]): string[] {
    return browsingHistory
        .filter((page): page is WebsiteBrowsingHistoryProdInterest => page in PROD_INTEREST_LABELS)
        .map((page) => PROD_INTEREST_LABELS[page])
}

/** Checks if a browsing history item is a known prod_interest value. */
export function isValidProdInterest(value: string): value is WebsiteBrowsingHistoryProdInterest {
    return value in PROD_INTEREST_TO_PRODUCT
}

/**
 * Reads the browsing history from PostHog's `prod_interest` super property.
 * Returns an empty array if not available.
 */
export function getBrowsingHistoryFromPostHog(): string[] {
    const prodInterest = window.posthog?.get_property?.('prod_interest')
    if (Array.isArray(prodInterest)) {
        return prodInterest.filter(isValidProdInterest)
    }
    return []
}
