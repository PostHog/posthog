import { useActions } from 'kea'

import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { PersonType } from '~/types'

interface DeletePersonButtonProps {
    person: PersonType
}
export function DeletePersonButton({ person }: DeletePersonButtonProps): JSX.Element {
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { loadData } = useActions(dataNodeLogic)
    return (
        <LemonButton
            onClick={() => showPersonDeleteModal(person, () => loadData())}
            icon={<IconTrash />}
            status="danger"
            size="small"
            data-attr="delete-person"
        />
    )
}
