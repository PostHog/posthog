import { DashboardFilter, HogQLVariable, QuerySchema } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { ActionType, DashboardType, EventDefinition, InsightShortId, QueryBasedInsightModel } from '~/types'

export type InsightWithQuery = Pick<Partial<QueryBasedInsightModel>, 'query'> & Partial<QueryBasedInsightModel>

export interface MaxInsightContext {
    type: 'insight'
    id: InsightShortId
    name?: string
    description?: string
    query: QuerySchema // The actual query node, e.g., TrendsQuery, HogQLQuery
}

export interface MaxDashboardContext {
    type: 'dashboard'
    id: number
    name?: string
    description?: string
    insights: MaxInsightContext[]
    filters: DashboardFilter
}

export interface MaxEventContext {
    type: 'event'
    id: string
    name?: string
    description?: string
}

export interface MaxActionContext {
    type: 'action'
    id: number
    name: string
    description?: string
}

// The main shape for the UI context sent to the backend
export interface MaxContextShape {
    dashboards?: MaxDashboardContext[]
    insights?: MaxInsightContext[]
    events?: MaxEventContext[]
    actions?: MaxActionContext[]
    filters_override?: DashboardFilter
    variables_override?: Record<string, HogQLVariable>
}

// Taxonomic filter options
export interface MaxContextOption {
    id: string
    value: string | integer
    name: string
    icon: React.ReactNode
    type?: 'dashboard' | 'insight' | 'event' | 'action'
}

// Union type for all possible context items that can be exposed by scene logics
export type MaxContextItem = MaxInsightContext | MaxDashboardContext | MaxEventContext | MaxActionContext

type RawInsightContextItem = {
    type: 'insight'
    data: InsightWithQuery
}
type RawDashboardContextItem = {
    type: 'dashboard'
    data: DashboardType<QueryBasedInsightModel>
}
type RawEventContextItem = {
    type: 'event'
    data: EventDefinition
}
type RawActionContextItem = {
    type: 'action'
    data: ActionType
}
export type RawMaxContextItem =
    | RawInsightContextItem
    | RawDashboardContextItem
    | RawEventContextItem
    | RawActionContextItem

// Helper type for maxContext selectors - ensures all scene logics return the same type
export type MaxContextSelector = RawMaxContextItem[]

/**
 * Helper functions to create maxContext items safely
 * These ensure proper typing and consistent patterns across scene logics
 */
export const createMaxContextHelpers = {
    dashboard: (dashboard: DashboardType<QueryBasedInsightModel>): RawDashboardContextItem => ({
        type: 'dashboard',
        data: dashboard,
    }),

    insight: (insight: InsightWithQuery): RawInsightContextItem => ({
        type: 'insight',
        data: insight,
    }),

    event: (event: EventDefinition): RawEventContextItem => ({
        type: 'event',
        data: event,
    }),

    action: (action: ActionType): RawActionContextItem => ({
        type: 'action',
        data: action,
    }),
}
