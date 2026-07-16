import { useActions } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { addExperimentsToNotebookModalLogic } from '../AddExperimentsToNotebookModal/addExperimentsToNotebookModalLogic'
import { ExperimentsNotebookTable } from '../AddExperimentsToNotebookModal/ExperimentsNotebookTable'

export type MarkdownNotebookExperimentPickerProps = {
    isOpen: boolean
    onClose: () => void
    onSelect: (experimentId: number) => void
}

export function MarkdownNotebookExperimentPicker({
    isOpen,
    onClose,
    onSelect,
}: MarkdownNotebookExperimentPickerProps): JSX.Element {
    const { loadExperiments, closeModal } = useActions(addExperimentsToNotebookModalLogic)

    // The table reads from the shared experiments logic, so this picker drives its lifecycle: load on
    // open, and reset filters on close so a stale search query doesn't carry over to the next open.
    // `closeModal` resets the filters without triggering a fetch (no listener).
    useEffect(() => {
        if (isOpen) {
            loadExperiments()
        } else {
            closeModal()
        }
    }, [isOpen, loadExperiments, closeModal])

    return (
        <LemonModal
            title="Add experiment to notebook"
            onClose={onClose}
            isOpen={isOpen}
            footer={
                <LemonButton type="secondary" data-attr="markdown-notebook-experiment-cancel" onClick={onClose}>
                    Close
                </LemonButton>
            }
        >
            <ExperimentsNotebookTable onSelect={onSelect} />
        </LemonModal>
    )
}
