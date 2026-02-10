import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { SavedInsightsTable } from './SavedInsightsTable'
import { DashboardActionButton } from './components/DashboardActionButton'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const isExperimentEnabled = useFeatureFlag('PRODUCT_ANALYTICS_ADD_INSIGHT_TO_DASHBOARD_MODAL', 'test')
    const { dashboard } = useValues(dashboardLogic)

    if (isExperimentEnabled) {
        return <SavedInsightsTable dashboard={dashboard} />
    }

    return <SavedInsightsTable renderActionColumn={(insight) => <DashboardActionButton insight={insight} />} />
}
