import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CohortTypeEnum } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { CohortCriteriaGroups } from 'scenes/cohorts/CohortFilters/CohortCriteriaGroups'
import { COHORT_TYPE_OPTIONS } from 'scenes/cohorts/CohortFilters/constants'

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
 * Inline "Create new cohort" modal for use inside the TaxonomicFilter. Reuses
 * `cohortEditLogic` so the form, validation, and API save path are identical to
 * the cohort creation scene at `/cohorts/new` — only the chrome is different.
 */
export function CohortCreateModal({ isOpen, onClose, onSaved, modalKey }: CohortCreateModalProps): JSX.Element | null {
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

    // Only mount the cohort edit logic while the modal is open — keeps the
    // logic isolated and avoids accidentally seeding the NEW_COHORT state when
    // the TaxonomicFilter is rendered but the modal is closed.
    if (!isOpen) {
        return null
    }

    return (
        <BindLogic logic={cohortEditLogic} props={logicProps}>
            <CohortCreateModalInner onClose={onClose} />
        </BindLogic>
    )
}

function CohortCreateModalInner({ onClose }: { onClose: () => void }): JSX.Element {
    const { cohort, cohortLoading } = useValues(cohortEditLogic)
    const { setCohortValue, setOuterGroupsType, submitCohort } = useActions(cohortEditLogic)

    return (
        <LemonModal
            title="Create new cohort"
            isOpen
            onClose={onClose}
            width={720}
            closable={!cohortLoading}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={onClose} disabled={cohortLoading}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => submitCohort()}
                        loading={cohortLoading}
                        data-attr="save-cohort-modal"
                        disabledReason={
                            cohort.is_static ? 'Static cohorts must be created from the cohorts page' : undefined
                        }
                    >
                        Create cohort
                    </LemonButton>
                </div>
            }
        >
            <Form logic={cohortEditLogic} formKey="cohort" enableFormOnSubmit className="deprecated-space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput
                        placeholder="e.g. Active users"
                        data-attr="cohort-name-modal"
                        autoFocus
                        onChange={(value) => setCohortValue('name', value)}
                        value={cohort.name ?? ''}
                    />
                </LemonField>
                <LemonField name="is_static" label="Type">
                    {({ value, onChange }) => (
                        <LemonSelect
                            options={COHORT_TYPE_OPTIONS}
                            value={value ? CohortTypeEnum.Static : CohortTypeEnum.Dynamic}
                            onChange={(cohortType) => {
                                onChange(cohortType === CohortTypeEnum.Static)
                            }}
                            fullWidth
                            data-attr="cohort-type-modal"
                        />
                    )}
                </LemonField>
                {cohort.is_static ? (
                    <div className="text-secondary">
                        Static cohorts require a CSV upload or persons picker. Please use the{' '}
                        <Link to="/cohorts/new" target="_blank">
                            full cohort editor
                        </Link>{' '}
                        to create a static cohort.
                    </div>
                ) : (
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
                )}
            </Form>
        </LemonModal>
    )
}
