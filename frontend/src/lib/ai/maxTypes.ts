import { Node } from '~/queries/schema/schema-general'

// Context for a single insight, to be used by Max
export interface InsightContextForMax {
    id: string | number
    name?: string
    description?: string

    query: Node // The actual query node, e.g., TrendsQuery, HogQLQuery

    insight_type?: string
}

// Context for a dashboard being viewed
export interface DashboardDisplayContext {
    id: string | number
    name?: string
    description?: string
}

// Container for multiple active insights, typically on a dashboard
// Keyed by a unique identifier for the insight on the dashboard (e.g., dashboard_item_id)
export interface MultiInsightContainer {
    [insightKey: string]: InsightContextForMax
}

export interface MaxNavigationContext {
    path: string
    page_title?: string
}

// The main shape for the UI context sent to the backend
export interface MaxContextShape {
    active_dashboard?: DashboardDisplayContext | null

    // Context for multiple insights, especially when a dashboard is in primaryFocus
    active_insights?: MultiInsightContainer | null

    // General information that's always good to have, if available
    global_info?: {
        navigation?: MaxNavigationContext
    }
}
