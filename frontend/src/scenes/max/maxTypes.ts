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
