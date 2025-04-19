import { IconTrash } from '@posthog/icons'
import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { groupDeleteModalLogic, GroupPartial } from '~/scenes/groups/groupDeleteModalLogic'

interface DeleteGroupButtonProps {
    group: GroupPartial
}
export function DeleteGroupButton({ group }: DeleteGroupButtonProps): JSX.Element {
    const { showGroupDeleteModal } = useActions(groupDeleteModalLogic)
    const { loadData } = useActions(dataNodeLogic)
    return (
        <LemonButton
            onClick={() => showGroupDeleteModal(group, () => loadData())}
            icon={<IconTrash />}
            status="danger"
            size="small"
            data-attr="delete-group"
        />
    )
}
