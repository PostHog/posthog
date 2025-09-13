import { useActions } from 'kea'

import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { cohortEditLogic } from '~/scenes/cohorts/cohortEditLogic'
import { PersonType } from '~/types'

interface RemovePersonFromCohortButtonProps {
    person: PersonType
    cohortId: number
}

export function RemovePersonFromCohortButton({ person, cohortId }: RemovePersonFromCohortButtonProps): JSX.Element {
    const { removePersonFromCohort } = useActions(cohortEditLogic({ id: cohortId }))

    const handleRemoveClick = (): void => {
        LemonDialog.open({
            title: 'Remove person from cohort',
            description: (
                <div>
                    Are you sure you want to remove{' '}
                    <strong>{person.properties?.email || person.distinct_ids?.[0] || 'this person'}</strong> from this
                    cohort?
                    <br />
                    This action cannot be undone.
                </div>
            ),
            primaryButton: {
                type: 'primary',
                status: 'danger',
                children: 'Remove',
                onClick: () => {
                    const personId = person.uuid || person.id
                    if (!personId) {
                        console.error('No person ID found:', person)
                        return
                    }

                    removePersonFromCohort(personId)
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <LemonButton
            onClick={handleRemoveClick}
            icon={<IconTrash />}
            status="danger"
            size="small"
            data-attr="remove-person-from-cohort"
            tooltip="Remove from cohort"
        />
    )
}
