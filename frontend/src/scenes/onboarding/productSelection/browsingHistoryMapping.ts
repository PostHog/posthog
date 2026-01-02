import { ProductKey } from '~/queries/schema/schema-general'

import { availableOnboardingProducts } from '../utils'

// Known prod_interest values from posthog.com
export type ProdInterest =
    | 'product-analytics'
    | 'web-analytics'
    | 'session-replay'
    | 'feature-flags'
    | 'experiments'
    | 'error-tracking'
    | 'surveys'
    | 'data-warehouse'
    | 'llm-analytics'
    | 'revenue-analytics'
    | 'workflows'
    | 'logs'
    | 'endpoints'

// Mapping from browsing history slugs to ProductKey values
const BROWSING_HISTORY_TO_PRODUCT: Record<ProdInterest, ProductKey | null> = {
    'product-analytics': ProductKey.PRODUCT_ANALYTICS,
    'web-analytics': ProductKey.WEB_ANALYTICS,
    'session-replay': ProductKey.SESSION_REPLAY,
    'feature-flags': ProductKey.FEATURE_FLAGS,
    experiments: ProductKey.EXPERIMENTS,
    'error-tracking': ProductKey.ERROR_TRACKING,
    surveys: ProductKey.SURVEYS,
    'data-warehouse': ProductKey.DATA_WAREHOUSE,
    'llm-analytics': ProductKey.LLM_ANALYTICS,
    // These don't have onboarding products yet
    'revenue-analytics': null,
    workflows: null,
    logs: null,
    endpoints: null,
}

// Human-readable names for browsing history items
const BROWSING_HISTORY_LABELS: Record<ProdInterest, string> = {
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
        .map((page) => BROWSING_HISTORY_TO_PRODUCT[page as ProdInterest])
        .filter((key): key is ProductKey => key !== null && key !== undefined)
        // Only include products available in onboarding
        .filter((key) => key in availableOnboardingProducts)

    // Remove duplicates
    return [...new Set(products)]
}

/**
 * Gets human-readable labels for browsing history items.
 */
export function getBrowsingHistoryLabels(browsingHistory: string[]): string[] {
    return browsingHistory
        .filter((page): page is ProdInterest => page in BROWSING_HISTORY_LABELS)
        .map((page) => BROWSING_HISTORY_LABELS[page])
}

/**
 * Checks if a browsing history item is a known prod_interest value.
 */
export function isValidProdInterest(value: string): value is ProdInterest {
    return value in BROWSING_HISTORY_TO_PRODUCT
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
