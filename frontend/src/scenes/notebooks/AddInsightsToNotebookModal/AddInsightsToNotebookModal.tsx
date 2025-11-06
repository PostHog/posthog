import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { AddSavedInsightsToNotebook } from 'scenes/saved-insights/AddSavedInsightsToNotebook'

import { addInsightsToNotebookModalLogic } from './addInsightsToNotebookModalLogic'

export function AddInsightsToNotebookModal(): JSX.Element {
    const { toggleIsAddInsightsToNotebookModalOpen } = useActions(addInsightsToNotebookModalLogic)
    const { isAddInsightsToNotebookModalOpen } = useValues(addInsightsToNotebookModalLogic)

    return (
        <LemonModal
            title="Add insight to notebook"
            onClose={toggleIsAddInsightsToNotebookModalOpen}
            isOpen={isAddInsightsToNotebookModalOpen}
            footer={
                <LemonButton
                    type="secondary"
                    data-attr="notebook-cancel"
                    onClick={toggleIsAddInsightsToNotebookModalOpen}
                    children="Close"
                />
            }
        >
            <AddSavedInsightsToNotebook />
        </LemonModal>
    )
}
