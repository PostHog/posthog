import { DashboardFilter, HogQLVariable, QuerySchema } from '~/queries/schema/schema-general'

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

// The main shape for the UI context sent to the backend
export interface MaxContextShape {
    dashboards?: MaxDashboardContext[]
    insights?: MaxInsightContext[]
    filters_override?: DashboardFilter
    variables_override?: Record<string, HogQLVariable>
}

// Taxonomic filter options
export interface MaxContextOption {
    id: string
    value: string | number
    name: string
    icon: React.ReactNode
    type?: 'dashboard' | 'insight'
    items?: {
        insights?: MaxInsightContext[]
        dashboards?: MaxDashboardContext[]
    }
}
