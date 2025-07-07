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

export interface MaxInsightContextPayload {
    type: MaxContextType.INSIGHT
    id: InsightShortId
    name?: string
    description?: string
    query: QuerySchema // The actual query node, e.g., TrendsQuery, HogQLQuery
}

export interface MaxDashboardContextPayload {
    type: MaxContextType.DASHBOARD
    id: number
    name?: string
    description?: string
    insights: MaxInsightContextPayload[]
    filters: DashboardFilter
}

export interface MaxEventContextPayload {
    type: MaxContextType.EVENT
    id: string
    name?: string
    description?: string
}

export interface MaxActionContextPayload {
    type: MaxContextType.ACTION
    id: number
    name: string
    description?: string
}

// The main shape for the UI context sent to the backend
export interface MaxUIContext {
    dashboards?: MaxDashboardContextPayload[]
    insights?: MaxInsightContextPayload[]
    events?: MaxEventContextPayload[]
    actions?: MaxActionContextPayload[]
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
export type MaxContextPayload =
    | MaxInsightContextPayload
    | MaxDashboardContextPayload
    | MaxEventContextPayload
    | MaxActionContextPayload

type MaxInsightContext = {
    type: MaxContextType.INSIGHT
    data: InsightWithQuery
}
type MaxDashboardContext = {
    type: MaxContextType.DASHBOARD
    data: DashboardType<QueryBasedInsightModel>
}
type MaxEventContext = {
    type: MaxContextType.EVENT
    data: EventDefinition
}
type MaxActionContext = {
    type: MaxContextType.ACTION
    data: ActionType
}
export type MaxContextItem = MaxInsightContext | MaxDashboardContext | MaxEventContext | MaxActionContext

/**
 * Helper functions to create maxContext items safely
 * These ensure proper typing and consistent patterns across scene logics
 */
export const createMaxContextHelpers = {
    dashboard: (dashboard: DashboardType<QueryBasedInsightModel>): MaxDashboardContext => ({
        type: MaxContextType.DASHBOARD,
        data: dashboard,
    }),

    insight: (insight: InsightWithQuery): MaxInsightContext => ({
        type: MaxContextType.INSIGHT,
        data: insight,
    }),

    event: (event: EventDefinition): MaxEventContext => ({
        type: MaxContextType.EVENT,
        data: event,
    }),

    action: (action: ActionType): MaxActionContext => ({
        type: MaxContextType.ACTION,
        data: action,
    }),
}
