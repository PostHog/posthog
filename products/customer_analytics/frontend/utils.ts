import type { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { isEventsNode } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

const DEFINITION_PAGE_SIZE = 100

export const CUSTOMER_ANALYTICS_LOGIC_KEY = 'customerAnalytics'

export const buildDashboardItemId = (uniqueKey: string): InsightLogicProps['dashboardItemId'] => {
    return `new-AdHoc.customer-analytics.${uniqueKey}`
}

export function isPageviewWithoutFilters(event: SeriesNode): boolean {
    return isEventsNode(event) && event.event === '$pageview' && (!event.properties || event.properties.length === 0)
}

export const loadEveryPage = async <T>(
    loadPage: (params: { limit: number; offset: number }) => Promise<{ count: number; results: T[] }>
): Promise<T[]> => {
    const results: T[] = []
    let offset = 0
    let count = 1
    while (offset < count) {
        const page = await loadPage({ limit: DEFINITION_PAGE_SIZE, offset })
        count = page.count
        results.push(...page.results)
        if (page.results.length === 0) {
            break
        }
        offset += page.results.length
    }
    return results
}
