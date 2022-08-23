import React, { useState } from 'react'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import ReactDOM from 'react-dom'

interface SaveCohortModalProps {
    onSave: (title: string) => void
    onAfterClose?: () => void
}

function SaveCohortModal({ onSave, onAfterClose }: SaveCohortModalProps): JSX.Element {
    const [cohortTitle, setCohortTitle] = useState('')
    const [isOpen, setIsOpen] = useState(true)

    return (
        <LemonModal
            title="New Cohort"
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setIsOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabled={!cohortTitle}
                        onClick={() => {
                            onSave(cohortTitle)
                            setCohortTitle('')
                        }}
                    >
                        Save
                    </LemonButton>
                </>
            }
            onClose={() => setIsOpen(false)}
            onAfterClose={onAfterClose}
            isOpen={isOpen}
        >
            <div className="mb-4">
                <LemonInput
                    autoFocus
                    placeholder="Cohort name..."
                    value={cohortTitle}
                    data-attr="cohort-name"
                    onChange={setCohortTitle}
                />
            </div>
        </LemonModal>
    )
}

export type OpenSaveCohortModalProps = Omit<SaveCohortModalProps, 'onClose' | 'onAfterClose'>

export const openSaveCohortModal = (props: OpenSaveCohortModalProps): void => {
    const div = document.createElement('div')
    function destroy(): void {
        const unmountResult = ReactDOM.unmountComponentAtNode(div)
        if (unmountResult && div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    ReactDOM.render(<SaveCohortModal {...props} onAfterClose={destroy} />, div)
}
