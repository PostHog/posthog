import { LemonBanner, LemonButton, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export interface RenameViewReference {
    id: string
    name: string
    type?: string
}

export interface RenameViewModalProps {
    viewName: string
    name: string
    nameError?: string
    submitError?: string
    isSaving: boolean
    references: RenameViewReference[]
    referencesLoading: boolean
    referencesError: boolean
    inline?: boolean
    onNameChange: (name: string) => void
    onClose: () => void
    onSubmit: () => void
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
    name,
    nameError,
    submitError,
    isSaving,
    references,
    referencesLoading,
    referencesError,
    inline,
    onNameChange,
    onClose,
    onSubmit,
}: RenameViewModalProps): JSX.Element {
    const submit = (): void => {
        if (isSaving || referencesLoading) {
            return
        }
        onSubmit()
    }

    return (
        <LemonModal
            isOpen
            inline={inline}
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
                        onClick={submit}
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
                        onChange={onNameChange}
                        onPressEnter={submit}
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
                                                <Link to={urls.nodeDetail(reference.id)} target="_blank">
                                                    {reference.name}
                                                </Link>
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
