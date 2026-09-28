import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonCheckbox } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { cohortEditLogic } from '~/scenes/cohorts/cohortEditLogic'

// Matches DEFAULT_COHORT_INSERT_BATCH_SIZE on the backend.
const MAX_PERSONS_TO_REMOVE = 1000

export interface PersonDisplayNameType {
    display_name: string
    id: string
}

interface RemovePersonFromCohortButtonProps {
    person: PersonDisplayNameType
}

export function RemovePersonFromCohortButton({ person }: RemovePersonFromCohortButtonProps): JSX.Element {
    const { removePersonFromCohort, togglePersonToRemoveFromCohort } = useActions(cohortEditLogic)
    const { personsToRemoveFromCohort } = useValues(cohortEditLogic)

    const handleRemoveClick = (): void => {
        LemonDialog.open({
            title: 'Remove person from cohort',
            description: (
                <>
                    <p className="mt-4">
                        Are you sure you want to remove{' '}
                        <strong>{person.display_name === person.id ? 'Anonymous' : person.display_name}</strong> from
                        this cohort?
                    </p>
                    <p>This action cannot be undone.</p>
                </>
            ),
            primaryButton: {
                type: 'primary',
                status: 'danger',
                children: 'Remove',
                onClick: () => {
                    if (!person.id) {
                        return
                    }
                    removePersonFromCohort(person.id)
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <div className="flex items-center gap-1">
            <LemonCheckbox
                checked={person.id in personsToRemoveFromCohort}
                onChange={() => togglePersonToRemoveFromCohort(person.id)}
                data-attr="select-person-to-remove-from-cohort"
            />
            <LemonButton
                onClick={handleRemoveClick}
                icon={<IconTrash />}
                status="danger"
                size="small"
                data-attr="remove-person-from-cohort"
                tooltip="Remove from cohort"
            />
        </div>
    )
}

export function RemoveSelectedPersonsFromCohortBar(): JSX.Element | null {
    const { removeSelectedPersonsFromCohort, resetPersonsToRemoveFromCohort } = useActions(cohortEditLogic)
    const { personsToRemoveFromCohort, removingPersonsFromCohort } = useValues(cohortEditLogic)
    const selectedCount = Object.keys(personsToRemoveFromCohort).length

    if (selectedCount === 0) {
        return null
    }

    const peopleLabel = `${selectedCount} ${selectedCount === 1 ? 'person' : 'people'}`

    const handleRemoveClick = (): void => {
        LemonDialog.open({
            title: 'Remove people from cohort',
            description: (
                <>
                    <p className="mt-4">
                        Are you sure you want to remove <strong>{peopleLabel}</strong> from this cohort?
                    </p>
                    <p>This action cannot be undone.</p>
                </>
            ),
            primaryButton: {
                type: 'primary',
                status: 'danger',
                children: 'Remove',
                onClick: removeSelectedPersonsFromCohort,
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className="text-secondary">{peopleLabel} selected</span>
            <LemonButton
                type="secondary"
                status="danger"
                size="small"
                icon={<IconTrash />}
                onClick={handleRemoveClick}
                loading={removingPersonsFromCohort}
                disabledReason={
                    selectedCount > MAX_PERSONS_TO_REMOVE
                        ? `Select ${MAX_PERSONS_TO_REMOVE} people or fewer to remove at once`
                        : undefined
                }
                data-attr="remove-selected-persons-from-cohort"
            >
                Remove selected
            </LemonButton>
            <LemonButton
                type="tertiary"
                size="small"
                onClick={resetPersonsToRemoveFromCohort}
                disabledReason={removingPersonsFromCohort ? 'Removing people' : undefined}
            >
                Clear selection
            </LemonButton>
        </div>
    )
}
