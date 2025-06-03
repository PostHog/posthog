import { Node } from '~/queries/schema/schema-general'

export interface InsightContextForMax {
    id: string | number
    name?: string
    description?: string

    query: Node // The actual query node, e.g., TrendsQuery, HogQLQuery

    insight_type?: string
}

export interface DashboardContextForMax {
    id: string | number
    name?: string
    description?: string
    insights: InsightContextForMax[]
}

export interface MultiDashboardContextContainer {
    [dashboardKey: string]: DashboardContextForMax
}

export interface MultiInsightContextContainer {
    [insightKey: string]: InsightContextForMax
}

export interface MaxNavigationContext {
    path: string
    page_title?: string
}

// The main shape for the UI context sent to the backend
export interface MaxContextShape {
    dashboards?: MultiDashboardContextContainer
    insights?: MultiInsightContextContainer

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
