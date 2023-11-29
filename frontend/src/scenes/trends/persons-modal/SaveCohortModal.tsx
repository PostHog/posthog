import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { useState } from 'react'

interface Props {
    onSave: (title: string) => void
    onCancel: () => void
    isOpen: boolean
}

export function SaveCohortModal({ onSave, onCancel, isOpen }: Props): JSX.Element {
    const [cohortTitle, setCohortTitle] = useState('')
    return (
        <LemonModal
            title="New cohort"
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel}>
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
            onClose={onCancel}
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
