import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'

export interface RenameViewReference {
    id: string
    name: string
    type?: string
}

export interface RenameViewModalProps {
    viewName: string
    references: RenameViewReference[]
    referencesLoading: boolean
    referencesError: boolean
    isNameTaken: (name: string) => boolean
    validateName: (name: string) => string | undefined
    onClose: () => void
    onSubmit: (name: string) => Promise<void>
}

function getReferenceTypeLabel(type?: string): string {
    switch (type) {
        case 'table':
            return 'Table'
        case 'view':
            return 'View'
        case 'matview':
            return 'Materialized view'
        case 'endpoint':
            return 'Endpoint'
        case 'metric':
            return 'Metric'
        default:
            return type ? type.replaceAll('_', ' ') : 'Reference'
    }
}

export function RenameViewModal({
    viewName,
    references,
    referencesLoading,
    referencesError,
    isNameTaken,
    validateName,
    onClose,
    onSubmit,
}: RenameViewModalProps): JSX.Element {
    const [name, setName] = useState(viewName)
    const [nameError, setNameError] = useState<string>()
    const [submitError, setSubmitError] = useState<string>()
    const [isSaving, setIsSaving] = useState(false)

    const submit = async (): Promise<void> => {
        if (isSaving || referencesLoading) {
            return
        }

        const newName = name.trim()
        const validationError = validateName(newName)
        if (validationError) {
            setNameError(validationError)
            return
        }
        if (newName !== viewName && isNameTaken(newName)) {
            setNameError('A view with this name already exists')
            return
        }
        if (newName === viewName) {
            onClose()
            return
        }

        setNameError(undefined)
        setSubmitError(undefined)
        setIsSaving(true)
        try {
            await onSubmit(newName)
            onClose()
        } catch (error) {
            setSubmitError(error instanceof Error ? error.message : 'Could not rename the view. Try again.')
        } finally {
            setIsSaving(false)
        }
    }

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            closable={!isSaving}
            title="Rename view"
            width={560}
            hasUnsavedInput={name.trim() !== viewName}
            data-attr="data-warehouse-rename-view-modal"
            footer={
                <>
                    <LemonButton type="tertiary" onClick={onClose} disabledReason={isSaving ? 'Renaming view' : null}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isSaving}
                        disabledReason={referencesLoading ? 'Loading known references' : undefined}
                        onClick={() => void submit()}
                        data-attr="data-warehouse-rename-view-submit"
                    >
                        Rename view
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3">
                <LemonField.Pure label="View name" error={nameError}>
                    <LemonInput
                        value={name}
                        onChange={(value) => {
                            setName(value)
                            setNameError(undefined)
                        }}
                        onPressEnter={() => void submit()}
                        disabled={isSaving}
                        autoFocus
                    />
                </LemonField.Pure>

                {referencesLoading ? (
                    <div className="flex items-center gap-2 text-secondary text-sm">
                        <Spinner />
                        <span>Loading known references</span>
                    </div>
                ) : referencesError ? (
                    <p className="text-danger text-sm">Could not load known references from data model lineage.</p>
                ) : references.length > 0 ? (
                    <LemonCollapse
                        panels={[
                            {
                                key: 'references',
                                header: `Known references (${references.length})`,
                                content: (
                                    <ul className="space-y-1 text-sm">
                                        {references.map((reference) => (
                                            <li key={reference.id} className="break-words">
                                                <span className="text-secondary">
                                                    {getReferenceTypeLabel(reference.type)}:
                                                </span>{' '}
                                                {reference.name}
                                            </li>
                                        ))}
                                    </ul>
                                ),
                            },
                        ]}
                    />
                ) : (
                    <p className="text-secondary text-sm">No downstream references found in data model lineage.</p>
                )}

                <LemonBanner type="warning" alignItems="start">
                    This changes the view name only. SQL in saved views, materialized views, endpoints, insights,
                    dashboards, notebooks, and external systems is not updated and can stop working after the rename.
                </LemonBanner>

                {submitError ? <p className="text-danger text-sm">{submitError}</p> : null}
            </div>
        </LemonModal>
    )
}
