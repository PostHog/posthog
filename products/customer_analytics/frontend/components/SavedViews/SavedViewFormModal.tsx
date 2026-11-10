import type { ReactNode } from 'react'

import { IconGlobe, IconUser } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

interface SavedViewFormModalProps {
    isOpen: boolean
    isEditing: boolean
    isSaving: boolean
    description?: string
    placeholder: string
    onClose: () => void
    onSubmit: () => void
    renderForm: (fields: ReactNode) => ReactNode
}

export function SavedViewFormModal({
    isOpen,
    isEditing,
    isSaving,
    description,
    placeholder,
    onClose,
    onSubmit,
    renderForm,
}: SavedViewFormModalProps): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={isEditing ? 'Edit view' : 'Save as new view'}
            description={isEditing ? undefined : description}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        loading={isSaving}
                        disabledReason={isSaving ? 'Saving...' : undefined}
                    >
                        {isEditing ? 'Save changes' : 'Save view'}
                    </LemonButton>
                </>
            }
        >
            {renderForm(
                <div className="space-y-4">
                    <LemonField name="name" label="View name">
                        <LemonInput
                            placeholder={placeholder}
                            autoFocus
                            onPressEnter={isSaving ? undefined : onSubmit}
                        />
                    </LemonField>
                    <LemonField name="visibility" label="Visibility">
                        <LemonSegmentedButton
                            options={[
                                { value: 'private', label: 'Private (only visible to me)', icon: <IconUser /> },
                                { value: 'shared', label: 'Shared with team', icon: <IconGlobe /> },
                            ]}
                            fullWidth
                        />
                    </LemonField>
                </div>
            )}
        </LemonModal>
    )
}
