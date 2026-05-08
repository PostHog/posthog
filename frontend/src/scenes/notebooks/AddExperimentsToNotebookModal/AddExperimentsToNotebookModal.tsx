import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { addExperimentsToNotebookModalLogic } from './addExperimentsToNotebookModalLogic'
import { ExperimentsNotebookTable } from './ExperimentsNotebookTable'

export function AddExperimentsToNotebookModal(): JSX.Element {
    const { closeModal } = useActions(addExperimentsToNotebookModalLogic)
    const { isAddExperimentsToNotebookModalOpen, insertionPosition } = useValues(addExperimentsToNotebookModalLogic)

    return (
        <LemonModal
            title="Add experiment to notebook"
            onClose={closeModal}
            isOpen={isAddExperimentsToNotebookModalOpen}
            footer={<LemonButton type="secondary" data-attr="notebook-cancel" onClick={closeModal} children="Close" />}
        >
            <ExperimentsNotebookTable insertionPosition={insertionPosition} />
        </LemonModal>
    )
}
