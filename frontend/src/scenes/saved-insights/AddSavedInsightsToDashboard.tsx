import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { SavedInsightsTable } from './SavedInsightsTable'
import { DashboardActionButton } from './components/DashboardActionButton'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const isExperimentEnabled = useFeatureFlag('ADD_INSIGHT_TO_DASHBOARD_MODAL_EXPERIMENT')
    const { dashboard } = useValues(dashboardLogic)

    if (isExperimentEnabled) {
        return <SavedInsightsTable dashboardId={dashboard?.id} title="Or add an existing insight" />
    }

    return <SavedInsightsTable renderActionColumn={(insight) => <DashboardActionButton insight={insight} />} />
}
