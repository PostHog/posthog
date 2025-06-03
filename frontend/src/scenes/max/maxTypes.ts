import { Node } from '~/queries/schema/schema-general'
import { DashboardType, QueryBasedInsightModel } from '~/types'

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

// Container for multiple active insights, typically on a dashboard
// Keyed by a unique identifier for the insight on the dashboard (e.g., dashboard_item_id)
export interface MultiInsightContainer {
    [insightKey: string]: Partial<QueryBasedInsightModel>
}

export interface MultiDashboardContainer {
    [dashboardKey: string]: DashboardType<QueryBasedInsightModel>
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
    dashboards?: MultiDashboardContextContainer | null
    insights?: MultiInsightContextContainer | null

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
        insights?: Partial<QueryBasedInsightModel>[]
        dashboards?: DashboardType<QueryBasedInsightModel>[]
    }
}
