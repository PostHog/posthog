import { InsightLogicProps } from '~/types'

export const CUSTOMER_ANALYTICS_LOGIC_KEY = 'customerAnalytics'

export const buildDashboardItemId = (uniqueKey: string): InsightLogicProps['dashboardItemId'] => {
    return `new-AdHoc.customer-analytics.${uniqueKey}`
}
