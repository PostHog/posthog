import { ProductKey } from '~/types'

export type UseCaseOption =
    | 'see_user_behavior'
    | 'fix_issues'
    | 'launch_features'
    | 'collect_feedback'
    | 'monitor_ai'
    | 'pick_myself'

export const USE_CASE_PRODUCT_RECOMMENDATIONS: Record<UseCaseOption, ProductKey[]> = {
    // Use Case 1: "See what users are doing"
    // Session Replay for qualitative insights, Product Analytics for quantitative data
    see_user_behavior: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],

    // Use Case 2: "Find and fix issues"
    // Core debugging tools - see the session and catch errors
    fix_issues: [ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING],

    // Use Case 3: "Launch features with confidence"
    // Core feature launch tools - flags and experiments
    launch_features: [ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS],

    // Use Case 4: "Collect user feedback"
    // Surveys for direct feedback, Product Analytics to measure behavior
    collect_feedback: [ProductKey.SURVEYS, ProductKey.PRODUCT_ANALYTICS],

    // Use Case 5: "Monitor AI applications"
    // Specialist product for specialist use case
    monitor_ai: [ProductKey.LLM_ANALYTICS],

    // Option 6: "I want to pick products myself"
    // Skip directly to product selection with no pre-selection
    pick_myself: [],
}

// Note: Data Warehouse is NOT in any recommendations
// It's only available via "Show all products" button
// Why? It's an advanced product typically used by data teams
// who know they need it. Not a good starter product for onboarding.
// Users who need it will find it in the expanded list.

export function getRecommendedProducts(useCase: UseCaseOption | null | string): ProductKey[] {
    if (!useCase || useCase === 'pick_myself') {
        return []
    }
    return USE_CASE_PRODUCT_RECOMMENDATIONS[useCase as UseCaseOption] || []
}

export function getUseCaseLabel(useCase: UseCaseOption | null | string): string {
    const labels: Record<UseCaseOption, string> = {
        see_user_behavior: 'Understand how users behave',
        fix_issues: 'Find and fix issues',
        launch_features: 'Launch features with confidence',
        collect_feedback: 'Collect user feedback',
        monitor_ai: 'Monitor AI applications',
        pick_myself: 'I want to pick products myself',
    }
    return labels[useCase as UseCaseOption] || ''
}
