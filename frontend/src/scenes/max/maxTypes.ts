import { DashboardFilter, QuerySchema } from '~/queries/schema/schema-general'

export interface MaxInsightContext {
    id: string | number
    name?: string
    description?: string

    query: QuerySchema // The actual query node, e.g., TrendsQuery, HogQLQuery
}

export interface MaxDashboardContext {
    id: string | number
    name?: string
    description?: string
    insights: MaxInsightContext[]
    filters: DashboardFilter
}

export interface MultiDashboardContextContainer {
    [dashboardKey: string]: MaxDashboardContext
}

export interface MultiInsightContextContainer {
    [insightKey: string]: MaxInsightContext
}

// The main shape for the UI context sent to the backend
export interface MaxContextShape {
    dashboards?: MultiDashboardContextContainer
    insights?: MultiInsightContextContainer
}

// Taxonomic filter options
export interface MaxContextOption {
    value: string
    name: string
    icon: React.ReactNode
    items?: {
        insights?: MaxInsightContext[]
        dashboards?: MaxDashboardContext[]
    }
}
