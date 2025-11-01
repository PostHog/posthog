import { SavedInsightsTable } from './SavedInsightsTable'
import { NotebookActionButton } from './components/NotebookActionButton'

export function AddSavedInsightsToNotebook(): JSX.Element {
    return <SavedInsightsTable renderActionColumn={(insight) => <NotebookActionButton insight={insight} />} />
}
