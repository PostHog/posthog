import { useActions, useValues } from 'kea'

import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { QueryBasedInsightModel } from '~/types'

import { SavedInsightsTable } from './SavedInsightsTable'

export function AddSavedInsightsToNotebook({ insertionPosition }: { insertionPosition: number | null }): JSX.Element {
    const { insightShortIdsInNotebook } = useValues(notebookLogic)
    const { addSavedInsightToNotebook } = useActions(notebookLogic)

    return (
        <SavedInsightsTable
            isSelected={(insight: QueryBasedInsightModel) =>
                insightShortIdsInNotebook?.includes(insight.short_id) ?? false
            }
            onToggle={(insight: QueryBasedInsightModel) =>
                addSavedInsightToNotebook(insight.short_id, insertionPosition)
            }
        />
    )
}
