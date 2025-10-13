import { RevenueAnalyticsBreakdown, RevenueAnalyticsGoal, RevenueAnalyticsPropertyFilters } from './schema-general'

// Revenue Analytics filters but in a way that's easier for the AI assistant to understand
export interface RevenueAnalyticsAssistantFilters {
    date_from?: string | null
    date_to?: string | null
    properties: RevenueAnalyticsPropertyFilters
    breakdown: RevenueAnalyticsBreakdown[]
}

export interface RevenueAnalyticsAssistantGoalsOutput {
    /**
     * Should only be listed when the revenue goals changed. If they haven't just use `null`.
     */
    goals: RevenueAnalyticsGoal[] | null
}
