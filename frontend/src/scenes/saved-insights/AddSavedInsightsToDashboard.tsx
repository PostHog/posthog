import { SavedInsightsTable } from './SavedInsightsTable'
import { DashboardActionButton } from './components/DashboardActionButton'

export function AddSavedInsightsToDashboard(): JSX.Element {
    return <SavedInsightsTable renderActionColumn={(insight) => <DashboardActionButton insight={insight} />} />
}
