import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { CohortCriteriaGroups } from 'scenes/cohorts/CohortFilters/CohortCriteriaGroups'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { CohortType } from '~/types'

export interface CohortCreateModalProps {
    isOpen: boolean
    onClose: () => void
    onSaved: (cohort: CohortType) => void
    /**
     * Unique key used to isolate this modal's `cohortEditLogic` instance from the
     * cohort scene (which keys by `id` + `tabId`). Typically the parent's
     * taxonomicFilterLogicKey.
     */
    modalKey: string
}

/**
 * Inline "New cohort" modal for use inside the TaxonomicFilter. Reuses
 * `cohortEditLogic` so the form, validation, and API save path are identical to
 * the cohort creation scene at `/cohorts/new` — only the chrome is different.
 *
 * This modal only supports dynamic cohorts. Static cohorts require a CSV upload
 * or persons picker and are handled by the full cohort scene.
 */
export function CohortCreateModal({ isOpen, onClose, onSaved, modalKey }: CohortCreateModalProps): JSX.Element {
    const logicProps = useMemo(
        () => ({
            id: 'new' as const,
            tabId: `cohort-create-modal-${modalKey}`,
            disableNavigation: true,
            onSaved: (cohort: CohortType) => {
                onSaved(cohort)
                onClose()
            },
        }),
        [modalKey, onSaved, onClose]
    )

    // Always render the modal (use LemonModal's isOpen to toggle visibility)
    // so a mid-save close never unmounts `cohortEditLogic` and orphans the
    // in-flight API call.
    return (
        <BindLogic logic={cohortEditLogic} props={logicProps}>
            <CohortCreateModalInner isOpen={isOpen} onClose={onClose} />
        </BindLogic>
    )
}

function CohortCreateModalInner({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { cohort, cohortLoading } = useValues(cohortEditLogic)
    const { setOuterGroupsType, submitCohort } = useActions(cohortEditLogic)

    const savingDisabledReason = cohortLoading ? 'Saving…' : undefined

    return (
        <LemonModal
            title="New cohort"
            isOpen={isOpen}
            onClose={onClose}
            width={720}
            // `.click-outside-block` prevents clicks inside the modal content
            // from closing a surrounding Popover (e.g. TaxonomicPopover) via its
            // click-outside handler. Without this, clicking any control in the
            // modal would dismiss the host filter popover and unmount the modal.
            overlayClassName={CLICK_OUTSIDE_BLOCK_CLASS}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => submitCohort()}
                        loading={cohortLoading}
                        disabledReason={savingDisabledReason}
                        data-attr="save-cohort-modal"
                    >
                        Create cohort
                    </LemonButton>
                </div>
            }
        >
            <Form logic={cohortEditLogic} formKey="cohort" enableFormOnSubmit className="deprecated-space-y-4">
                <LemonField name="name" label="Name">
                    {({ value, onChange }) => (
                        <LemonInput
                            placeholder="e.g. Active users"
                            data-attr="cohort-name-modal"
                            autoFocus
                            value={value ?? ''}
                            onChange={onChange}
                        />
                    )}
                </LemonField>
                <div className="text-xs text-secondary">
                    Need a static cohort (uploaded from a CSV)?{' '}
                    <Link to="/cohorts/new" target="_blank">
                        Use the full cohort editor
                    </Link>
                    .
                </div>
                <div className="flex flex-col gap-2">
                    <AndOrFilterSelect
                        value={cohort.filters.properties.type}
                        onChange={(value) => setOuterGroupsType(value)}
                        topLevelFilter
                        suffix={['criterion', 'criteria']}
                    />
                    <div className="[&>div]:my-0 [&>div]:w-full">
                        <CohortCriteriaGroups id="new" />
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
