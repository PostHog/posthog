import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

interface Props {
    onSave: (title: string) => void
    onCancel: () => void
    isOpen: boolean
    title?: string
    description?: string
}

export function SaveCohortModal({ onSave, onCancel, isOpen, title = 'New cohort', description }: Props): JSX.Element {
    const [cohortTitle, setCohortTitle] = useState('')
    return (
        <LemonModal
            title={title}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={!cohortTitle && 'Please add a title to your cohort'}
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
            {description && <p className="mb-2 text-secondary">{description}</p>}
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
