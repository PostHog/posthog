import { useValues } from 'kea'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { SavedInsightsTable } from './SavedInsightsTable'

export function AddSavedInsightsToDashboard(): JSX.Element {
    const { dashboard } = useValues(dashboardLogic)
    return <SavedInsightsTable dashboardId={dashboard?.id} title="Or add an existing insight" />
}
