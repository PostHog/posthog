import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { AddSavedInsightsToNotebook } from 'scenes/saved-insights/AddSavedInsightsToNotebook'

import { addInsightsToNotebookModalLogic } from './addInsightsToNotebookModalLogic'

export function AddInsightsToNotebookModal(): JSX.Element {
    const { closeModal } = useActions(addInsightsToNotebookModalLogic)
    const { isAddInsightsToNotebookModalOpen, insertionPosition } = useValues(addInsightsToNotebookModalLogic)

    return (
        <LemonModal
            title="Add insight to notebook"
            onClose={closeModal}
            isOpen={isAddInsightsToNotebookModalOpen}
            footer={<LemonButton type="secondary" data-attr="notebook-cancel" onClick={closeModal} children="Close" />}
        >
            <AddSavedInsightsToNotebook insertionPosition={insertionPosition} />
        </LemonModal>
    )
}
