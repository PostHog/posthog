import { Node } from '~/queries/schema/schema-general'

// Context for a single insight, to be used by Max
export interface InsightContextForMax {
    id: string | number
    name?: string
    description?: string

    query: Node // The actual query node, e.g., TrendsQuery, HogQLQuery

    insight_type?: string
}

// Context for a dashboard being viewed
export interface DashboardDisplayContext {
    id: string | number
    name?: string
    description?: string
}

// Container for multiple active insights, typically on a dashboard
// Keyed by a unique identifier for the insight on the dashboard (e.g., dashboard_item_id)
export interface MultiInsightContainer {
    [insightKey: string]: InsightContextForMax
}

// Simplified product information for Max context
export interface MaxProductInfo {
    type: string
    name: string
    description: string
    is_used: boolean // current_usage > 0
    has_exceeded_limit: boolean
    current_usage?: number
    usage_limit?: number | null
    percentage_usage: number
}

// Simplified addon information for Max context
export interface MaxAddonInfo {
    type: string
    name: string
    description: string
    is_used: boolean // current_usage > 0
    has_exceeded_limit: boolean
    current_usage: number
    usage_limit?: number | null
    percentage_usage?: number
    included_with_main_product?: boolean
}

// Comprehensive billing context for Max
export interface GlobalBillingContext {
    // Overall billing status
    has_active_subscription: boolean
    subscription_level: 'free' | 'paid' | 'custom'
    billing_plan: string | null
    is_deactivated?: boolean

    // Products information
    products: MaxProductInfo[]

    // Addons information (flattened from all products)
    addons: MaxAddonInfo[]

    // Usage summary
    total_current_amount_usd?: string
    total_projected_amount_usd?: string

    // Trial information
    trial?: {
        is_active: boolean
        expires_at?: string
        target?: string
    }

    // Billing period
    billing_period?: {
        current_period_start: string
        current_period_end: string
        interval: 'month' | 'year'
    }
}

export interface MaxNavigationContext {
    path: string
    page_title?: string
}

// The main shape for the UI context sent to the backend
export interface MaxContextShape {
    active_dashboard?: DashboardDisplayContext | null

    // Context for multiple insights, especially when a dashboard is in primaryFocus
    active_insights?: MultiInsightContainer | null

    // General information that's always good to have, if available
    global_info?: {
        billing?: GlobalBillingContext
        navigation?: MaxNavigationContext
    }
}
