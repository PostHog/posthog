import { RevenueAnalyticsBreakdown, RevenueAnalyticsPropertyFilters } from './schema-general'

// Revenue Analytics filters but in a way that's easier for the AI assistant to understand
export interface RevenueAnalyticsAssistantFilters {
    date_from?: string | null
    date_to?: string | null
    properties: RevenueAnalyticsPropertyFilters
    breakdown: RevenueAnalyticsBreakdown[]
}
