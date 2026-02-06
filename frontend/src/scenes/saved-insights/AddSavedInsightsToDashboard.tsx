import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SavedInsightsTable } from './SavedInsightsTable'
import { DashboardActionButton } from './components/DashboardActionButton'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const isExperimentEnabled = useFeatureFlag('PRODUCT_ANALYTICS_ADD_INSIGHT_TO_DASHBOARD_MODAL', 'test')

    if (isExperimentEnabled) {
        return <SavedInsightsTable />
    }

    return <SavedInsightsTable renderActionColumn={(insight) => <DashboardActionButton insight={insight} />} />
}
