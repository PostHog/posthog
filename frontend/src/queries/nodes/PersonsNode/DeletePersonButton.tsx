import { useActions } from 'kea'

import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { PersonType } from '~/types'

import { personDeleteModalLogic } from 'products/persons/frontend/logics/personDeleteModalLogic'

interface DeletePersonButtonProps {
    person: PersonType | null
}
export function DeletePersonButton({ person }: DeletePersonButtonProps): JSX.Element {
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { loadData } = useActions(dataNodeLogic)
    return (
        <LemonButton
            onClick={person ? () => showPersonDeleteModal(person, () => loadData()) : undefined}
            disabledReason={person ? undefined : 'Add the Person or ID column to delete this person'}
            icon={<IconTrash />}
            status="danger"
            size="small"
            data-attr="delete-person"
        />
    )
}
