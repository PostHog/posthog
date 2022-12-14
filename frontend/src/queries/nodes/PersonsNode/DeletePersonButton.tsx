import { LemonButton } from 'lib/components/LemonButton'
import { IconDelete } from 'lib/components/icons'
import { useActions } from 'kea'
import { PersonType } from '~/types'
import { personDeleteModalLogic } from 'scenes/persons/personDeleteModalLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

interface DeletePersonButtonProps {
    person: PersonType
}
export function DeletePersonButton({ person }: DeletePersonButtonProps): JSX.Element {
    const { showPersonDeleteModal } = useActions(personDeleteModalLogic)
    const { loadData } = useActions(dataNodeLogic)
    return (
        <LemonButton
            onClick={() => showPersonDeleteModal(person, () => loadData())}
            icon={<IconDelete />}
            status="danger"
            size="small"
        />
    )
}
