import { ProductKey } from '~/types'

export type UseCaseOption =
    | 'see_user_behavior'
    | 'fix_issues'
    | 'launch_features'
    | 'collect_feedback'
    | 'monitor_ai'
    | 'pick_myself'

export interface UseCaseDefinition {
    key: UseCaseOption
    title: string
    description: string
    iconKey: string
    iconColor: string
    products: readonly ProductKey[]
}

// Single source of truth for use case definitions
// Used by both UseCaseSelection.tsx UI and product recommendation logic
export const USE_CASE_OPTIONS: ReadonlyArray<UseCaseDefinition> = [
    {
        key: 'see_user_behavior',
        title: 'Understand how users behave',
        description: 'Understand user behavior with event-based analytics, cohorts, and conversion funnels',
        iconKey: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
    },
    {
        key: 'fix_issues',
        title: 'Find and fix issues',
        description: 'Track and monitor errors, then watch session recordings to see exactly what happened',
        iconKey: 'IconWarning',
        iconColor: 'rgb(235 157 42)',
        products: [ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING],
    },
    {
        key: 'launch_features',
        title: 'Launch features with confidence',
        description: 'Control feature rollouts and run A/B tests to see what performs best',
        iconKey: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        products: [ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS],
    },
    {
        key: 'collect_feedback',
        title: 'Collect user feedback',
        description: 'Collect feedback with in-app surveys and understand behavior with analytics',
        iconKey: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        products: [ProductKey.SURVEYS, ProductKey.PRODUCT_ANALYTICS],
    },
    {
        key: 'monitor_ai',
        title: 'Monitor AI applications',
        description: 'Monitor AI/LLM performance with traces, costs, and quality metrics',
        iconKey: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        products: [ProductKey.LLM_ANALYTICS],
    },
] as const

// 'pick_myself' is handled separately as it has no products or UI representation in the selection list

// Note: Data Warehouse is NOT in any recommendations
// It's only available via "Show all products" button
// Why? It's an advanced product typically used by data teams
// who know they need it. Not a good starter product for onboarding.
// Users who need it will find it in the expanded list.

export function getRecommendedProducts(useCase: UseCaseOption | null | string): readonly ProductKey[] {
    if (!useCase || useCase === 'pick_myself') {
        return []
    }
    const option = USE_CASE_OPTIONS.find((opt) => opt.key === useCase)
    return option?.products || []
}

export function getUseCaseLabel(useCase: UseCaseOption | null | string): string {
    if (useCase === 'pick_myself') {
        return 'I want to pick products myself'
    }
    const option = USE_CASE_OPTIONS.find((opt) => opt.key === useCase)
    return option?.title || ''
}
