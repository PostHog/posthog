import { SavedInsightsTable } from './SavedInsightsTable'
import { NotebookActionButton } from './components/NotebookActionButton'

export function AddSavedInsightsToNotebook({ insertionPosition }: { insertionPosition: number | null }): JSX.Element {
    return (
        <SavedInsightsTable
            renderActionColumn={(insight) => (
                <NotebookActionButton insight={insight} insertionPosition={insertionPosition} />
            )}
        />
    )
}
