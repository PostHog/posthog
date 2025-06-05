import { QuerySchema } from '~/queries/schema/schema-general'

export interface InsightContextForMax {
    id: string | number
    name?: string
    description?: string

    query: QuerySchema // The actual query node, e.g., TrendsQuery, HogQLQuery

    insight_type?: string
}

export interface DashboardContextForMax {
    id: string | number
    name?: string
    description?: string
    insights: InsightContextForMax[]
}

export interface EventContextForMax {
    id: string | number
    name?: string
    description?: string
}

export interface ActionContextForMax {
    id: string | number
    name?: string
    description?: string
}

export interface MultiDashboardContextContainer {
    [dashboardKey: string]: DashboardContextForMax
}

export interface MultiInsightContextContainer {
    [insightKey: string]: InsightContextForMax
}

export interface MultiEventContextContainer {
    [eventKey: string]: EventContextForMax
}

export interface MultiActionContextContainer {
    [actionKey: string]: ActionContextForMax
}

export interface MaxNavigationContext {
    path: string
    page_title?: string
}

// The main shape for the UI context sent to the backend
export interface MaxContextShape {
    dashboards?: MultiDashboardContextContainer
    insights?: MultiInsightContextContainer
    events?: MultiEventContextContainer
    actions?: MultiActionContextContainer

    // General information that's always good to have, if available
    global_info?: {
        navigation?: MaxNavigationContext
    }
}

// Taxonomic filter options
export interface MaxContextOption {
    value: string
    name: string
    icon: React.ReactNode
    items?: {
        insights?: InsightContextForMax[]
        dashboards?: DashboardContextForMax[]
    }
}
