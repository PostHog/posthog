import { DashboardFilter, HogQLVariable, QuerySchema } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { ActionType, DashboardType, EventDefinition, InsightShortId, QueryBasedInsightModel } from '~/types'

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

export type RawInsightContextItem = {
    type: 'insight'
    data: Pick<QueryBasedInsightModel, 'query'> & Partial<QueryBasedInsightModel>
}
export type RawDashboardContextItem = {
    type: 'dashboard'
    data: DashboardType<QueryBasedInsightModel>
}
export type RawEventContextItem = {
    type: 'event'
    data: EventDefinition
}
export type RawActionContextItem = {
    type: 'action'
    data: ActionType
}
export type RawMaxContextItem =
    | RawInsightContextItem
    | RawDashboardContextItem
    | RawEventContextItem
    | RawActionContextItem
