import { LemonBanner, LemonButton, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { SavedQueryRenamePlanApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { RenameViewQueryDiff } from './RenameViewQueryDiff'

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
    /** The models this rename rewrites, shown for review before the user confirms. */
    plan?: SavedQueryRenamePlanApi
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
    plan,
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
                        disabledReason={
                            referencesLoading
                                ? 'Loading known references'
                                : plan?.blocked.length
                                  ? 'Some views that reference this one cannot be updated'
                                  : undefined
                        }
                        onClick={submit}
                        data-attr="data-warehouse-rename-view-submit"
                    >
                        {plan?.dependents.length
                            ? `Rename and update ${plan.dependents.length} ${plan.dependents.length === 1 ? 'view' : 'views'}`
                            : !plan &&
                                references.some(
                                    (reference) => reference.type === 'view' || reference.type === 'matview'
                                )
                              ? 'Preview rename'
                              : 'Rename view'}
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

                {submitError ? <LemonBanner type="error">{submitError}</LemonBanner> : null}

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
                ) : null}

                {plan?.blocked.length ? (
                    <LemonBanner type="error" alignItems="start">
                        <p>
                            These views reference this one, and their SQL cannot be updated. Fix them, then try again.
                        </p>
                        <ul className="mt-1 space-y-1">
                            {plan.blocked.map((model) => (
                                <li key={model.id} className="break-words">
                                    <Link to={urls.nodeDetail(model.id)} target="_blank">
                                        {model.name}
                                    </Link>
                                    : {model.reason}
                                </li>
                            ))}
                        </ul>
                    </LemonBanner>
                ) : null}

                {plan?.dependents.length ? (
                    <div className="space-y-2" data-attr="data-warehouse-rename-view-plan">
                        <p className="text-sm">
                            These views reference this one. Their SQL is updated to the new name in the same change.
                        </p>
                        <LemonCollapse
                            multiple
                            panels={plan.dependents.map((model) => ({
                                key: model.id,
                                header: model.name,
                                content: <RenameViewQueryDiff before={model.before} after={model.after} />,
                            }))}
                        />
                    </div>
                ) : null}

                <LemonBanner type="warning" alignItems="start">
                    {references.length
                        ? 'Views that reference this one are updated with the new name. Endpoints, insights, dashboards, notebooks, and external systems are not updated and can stop working after the rename.'
                        : 'No other views reference this one. Endpoints, insights, dashboards, notebooks, and external systems are not checked and can stop working after the rename.'}
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
