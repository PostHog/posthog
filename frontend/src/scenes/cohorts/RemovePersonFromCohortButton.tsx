import { useActions } from 'kea'

import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { cohortEditLogic } from '~/scenes/cohorts/cohortEditLogic'

export interface PersonDisplayNameType {
    display_name: string
    id: string
}

interface RemovePersonFromCohortButtonProps {
    person: PersonDisplayNameType
}

export function RemovePersonFromCohortButton({ person }: RemovePersonFromCohortButtonProps): JSX.Element {
    const { removePersonFromCohort } = useActions(cohortEditLogic)

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
