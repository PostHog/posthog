import { ProductKey } from '~/queries/schema/schema-general'
import { UserRole } from '~/types'

export type UseCaseOption =
    | 'see_user_behavior'
    | 'fix_issues'
    | 'launch_features'
    | 'collect_feedback'
    | 'monitor_ai'
    | 'pick_myself'

export interface RoleRecommendation {
    role: UserRole
    banner: string
}

export interface UseCaseDefinition {
    key: UseCaseOption
    title: string
    description: string
    iconKey: string
    iconColor: string
    products: readonly ProductKey[]
    recommendedForRoles: readonly RoleRecommendation[]
}

// Single source of truth for use case definitions
// Used by both UseCaseSelection.tsx UI and product recommendation logic
// Note: Keep descriptions under 88 characters for better readability
export const USE_CASE_OPTIONS: ReadonlyArray<UseCaseDefinition> = [
    {
        key: 'see_user_behavior',
        title: 'Understand how users behave',
        description: 'Track website traffic and user behavior with analytics and conversion funnels',
        iconKey: 'IconGraph',
        iconColor: 'rgb(47 128 250)',
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.WEB_ANALYTICS],
        recommendedForRoles: [
            { role: UserRole.Marketing, banner: 'Great for marketers' },
            { role: UserRole.Product, banner: 'Great for PMs' },
            { role: UserRole.Data, banner: 'Great for data teams' },
            { role: UserRole.Founder, banner: 'Great for founders' },
            { role: UserRole.Leadership, banner: 'Great for leadership' },
        ],
    },
    {
        key: 'fix_issues',
        title: 'Find and fix issues',
        description: 'Watch session recordings and monitor errors to debug issues',
        iconKey: 'IconWarning',
        iconColor: 'rgb(235 157 42)',
        products: [ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING],
        recommendedForRoles: [],
    },
    {
        key: 'launch_features',
        title: 'Launch features with confidence',
        description: 'Roll out features gradually and run A/B tests to optimize your product',
        iconKey: 'IconToggle',
        iconColor: 'rgb(48 171 198)',
        products: [ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS],
        recommendedForRoles: [
            { role: UserRole.Engineering, banner: 'Great for engineers' },
            { role: UserRole.Product, banner: 'Great for PMs' },
        ],
    },
    {
        key: 'collect_feedback',
        title: 'Collect user feedback',
        description: 'Collect feedback with in-app surveys and watch session recordings',
        iconKey: 'IconMessage',
        iconColor: 'rgb(243 84 84)',
        products: [ProductKey.SURVEYS, ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        recommendedForRoles: [{ role: UserRole.Sales, banner: 'Great for sales teams' }],
    },
    {
        key: 'monitor_ai',
        title: 'Monitor AI applications',
        description: 'Track and analyze LLM usage, costs, and performance for AI applications',
        iconKey: 'IconLlmAnalytics',
        iconColor: 'rgb(182 42 217)',
        products: [ProductKey.LLM_ANALYTICS, ProductKey.PRODUCT_ANALYTICS],
        recommendedForRoles: [{ role: UserRole.Engineering, banner: 'Great for AI engineers' }],
    },
] as const

export function getRecommendedBanner(useCase: UseCaseDefinition, role: UserRole | null | undefined): string | null {
    if (!role) {
        return null
    }

    const match = useCase.recommendedForRoles.find((r) => r.role === role)
    return match?.banner ?? null
}

export function getSortedUseCases(role: UserRole | null | undefined): UseCaseDefinition[] {
    if (!role) {
        return [...USE_CASE_OPTIONS]
    }

    // We should sort matches above non-matches
    return [...USE_CASE_OPTIONS].sort((a, b) => {
        const scoreA = a.recommendedForRoles.some((r) => r.role === role) ? 1 : 0
        const scoreB = b.recommendedForRoles.some((r) => r.role === role) ? 1 : 0

        return scoreB - scoreA
    })
}

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
