import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SavedInsightsTable } from './SavedInsightsTable'
import { DashboardActionButton } from './components/DashboardActionButton'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const isExperimentEnabled = useFeatureFlag('ADD_INSIGHT_TO_DASHBOARD_MODAL_EXPERIMENT')

    if (isExperimentEnabled) {
        return <SavedInsightsTable title="Or add an existing insight" />
    }

    return <SavedInsightsTable renderActionColumn={(insight) => <DashboardActionButton insight={insight} />} />
}
