import { BillingUsageResponse } from 'scenes/billing/billingUsageLogic'

import { DashboardFilter, HogQLVariable, QuerySchema } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { ActionType, DashboardType, EventDefinition, InsightShortId, QueryBasedInsightModel } from '~/types'

export enum MaxContextType {
    DASHBOARD = 'dashboard',
    INSIGHT = 'insight',
    EVENT = 'event',
    ACTION = 'action',
}

export type InsightWithQuery = Pick<Partial<QueryBasedInsightModel>, 'query'> & Partial<QueryBasedInsightModel>

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
    custom_limit_usd?: number | null
    next_period_custom_limit_usd?: number | null
    docs_url?: string
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
    custom_limit_usd?: number | null
    next_period_custom_limit_usd?: number | null
    docs_url?: string
}

// Usage data context for Max
export interface MaxUsageContext {
    date_range: {
        start_date: string
        end_date: string
    }
    usage_summary: Array<{
        product_type: string
        product_name: string
        total_usage: number
        dates: string[]
        data: number[]
    }>
}

export interface MaxBillingContext {
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

    // Startup program
    startup_program_label?: string
    startup_program_label_previous?: string

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

    // Usage history
    usage_history?: BillingUsageResponse['results']

    // Settings
    settings: {
        autocapture_on: boolean
        active_destinations: number
    }
}

export interface MaxInsightContext {
    type: MaxContextType.INSIGHT
    id: InsightShortId
    name?: string | null
    description?: string | null
    query: QuerySchema // The actual query node, e.g., TrendsQuery, HogQLQuery
}

export interface MaxDashboardContext {
    type: MaxContextType.DASHBOARD
    id: number
    name?: string | null
    description?: string | null
    insights: MaxInsightContext[]
    filters: DashboardFilter
}

export interface MaxEventContext {
    type: MaxContextType.EVENT
    id: string
    name?: string | null
    description?: string | null
}

export interface MaxActionContext {
    type: MaxContextType.ACTION
    id: number
    name: string
    description?: string | null
}

// The main shape for the UI context sent to the backend
export interface MaxUIContext {
    dashboards?: MaxDashboardContext[]
    insights?: MaxInsightContext[]
    events?: MaxEventContext[]
    actions?: MaxActionContext[]
    filters_override?: DashboardFilter
    variables_override?: Record<string, HogQLVariable>
    billing?: MaxBillingContext
}

// Taxonomic filter options
export interface MaxContextTaxonomicFilterOption {
    id: string
    value: string | integer
    name: string
    icon: React.ReactNode
    type?: MaxContextType
}

// Union type for all possible context payloads that can be exposed by scene logics
export type MaxContextItem = MaxInsightContext | MaxDashboardContext | MaxEventContext | MaxActionContext

type MaxInsightContextInput = {
    type: MaxContextType.INSIGHT
    data: InsightWithQuery
}
type MaxDashboardContextInput = {
    type: MaxContextType.DASHBOARD
    data: DashboardType<QueryBasedInsightModel>
}
type MaxEventContextInput = {
    type: MaxContextType.EVENT
    data: EventDefinition
}
type MaxActionContextInput = {
    type: MaxContextType.ACTION
    data: ActionType
}
export type MaxContextInput =
    | MaxInsightContextInput
    | MaxDashboardContextInput
    | MaxEventContextInput
    | MaxActionContextInput

/**
 * Helper functions to create maxContext items safely
 * These ensure proper typing and consistent patterns across scene logics
 */
export const createMaxContextHelpers = {
    dashboard: (dashboard: DashboardType<QueryBasedInsightModel>): MaxDashboardContextInput => ({
        type: MaxContextType.DASHBOARD,
        data: dashboard,
    }),

    insight: (insight: InsightWithQuery): MaxInsightContextInput => ({
        type: MaxContextType.INSIGHT,
        data: insight,
    }),

    event: (event: EventDefinition): MaxEventContextInput => ({
        type: MaxContextType.EVENT,
        data: event,
    }),

    action: (action: ActionType): MaxActionContextInput => ({
        type: MaxContextType.ACTION,
        data: action,
    }),
}
