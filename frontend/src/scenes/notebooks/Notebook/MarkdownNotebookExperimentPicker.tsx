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
    const { loadExperiments } = useActions(addExperimentsToNotebookModalLogic)

    // The table reads from the shared experiments logic; the legacy modal seeds it on open, so this
    // picker (which doesn't toggle that modal's open state) must trigger the load itself.
    useEffect(() => {
        if (isOpen) {
            loadExperiments()
        }
    }, [isOpen, loadExperiments])

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
