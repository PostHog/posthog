import { CompareFilter, WebAnalyticsPropertyFilters } from './schema-general'

export interface WebAnalyticsAssistantFilters {
    date_from?: string | null
    date_to?: string | null
    properties: WebAnalyticsPropertyFilters
    doPathCleaning?: boolean
    compareFilter?: CompareFilter | null
}
