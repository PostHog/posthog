import { combineUrl } from 'kea-router'

import { LemonBanner, LemonButton, LemonInput, LemonModal, Spinner } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { DataModelingNodesRetrieveLookup } from 'products/data_modeling/frontend/generated/api.schemas'
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

// Lineage can be empty or unavailable while saved SQL still reads this view, so only the plan settles that none does.
function countOf(count: number, noun: string): string {
    return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function getSubmitLabel(references: RenameViewReference[], plan?: SavedQueryRenamePlanApi): string {
    const updates = [
        plan?.dependents.length ? countOf(plan.dependents.length, 'view') : null,
        plan?.joins.length ? countOf(plan.joins.length, 'join') : null,
    ].filter(Boolean)
    if (updates.length) {
        return `Rename and update ${updates.join(' and ')}`
    }
    if (!plan && references.some((reference) => reference.type === 'view' || reference.type === 'matview')) {
        return 'Preview rename'
    }
    return 'Rename view'
}

function getOtherReferencesWarning(references: RenameViewReference[], plan?: SavedQueryRenamePlanApi): string {
    const hasReaders = plan ? plan.dependents.length > 0 || plan.blocked.length > 0 : references.length > 0
    if (hasReaders) {
        return 'Views that reference this one are updated with the new name. Endpoints, insights, dashboards, notebooks, and external systems are not updated and can stop working after the rename.'
    }
    return plan
        ? 'No other views reference this one. Endpoints, insights, dashboards, notebooks, and external systems are not checked and can stop working after the rename.'
        : 'No known views reference this one. Endpoints, insights, dashboards, notebooks, and external systems are not checked and can stop working after the rename.'
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
                        {getSubmitLabel(references, plan)}
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
                                    <Link
                                        to={
                                            combineUrl(urls.nodeDetail(model.id), {
                                                lookup: DataModelingNodesRetrieveLookup.SavedQuery,
                                            }).url
                                        }
                                        target="_blank"
                                    >
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

                {plan?.joins.length ? (
                    <div className="space-y-1 text-sm" data-attr="data-warehouse-rename-view-plan-joins">
                        <p>These joins use this view. They are updated to the new name in the same change.</p>
                        <ul className="space-y-1">
                            {plan.joins.map((join) => (
                                <li key={join.id} className="break-words font-mono">
                                    {`${join.source_table_name_after}.${join.field_name} → ${join.joining_table_name_after}`}
                                </li>
                            ))}
                        </ul>
                    </div>
                ) : null}

                <LemonBanner type="warning" alignItems="start">
                    {getOtherReferencesWarning(references, plan)}
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
