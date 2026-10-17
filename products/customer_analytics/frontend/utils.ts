import type { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { isEventsNode } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

export const CUSTOMER_ANALYTICS_LOGIC_KEY = 'customerAnalytics'

export const buildDashboardItemId = (uniqueKey: string): InsightLogicProps['dashboardItemId'] => {
    return `new-AdHoc.customer-analytics.${uniqueKey}`
}

export function isPageviewWithoutFilters(event: SeriesNode): boolean {
    return isEventsNode(event) && event.event === '$pageview' && (!event.properties || event.properties.length === 0)
}
