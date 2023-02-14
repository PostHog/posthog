import { BindLogic, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

import { InsightsTable } from './InsightsTable'

/**
 * InsightsTable for use in a dashboard.
 */
export function DashboardInsightsTable(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    return (
        <BindLogic logic={trendsLogic} props={insightProps}>
            <InsightsTable
                filterKey={`dashboard_${insightProps.dashboardItemId}`}
                embedded
                canCheckUncheckSeries={false}
            />
        </BindLogic>
    )
}
