import { useActions, useValues } from 'kea'

import { userHasAccess } from 'lib/utils/accessControlUtils'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailHeader({ id }: { id: string }): JSX.Element {
    const { node, nodeLoading, savedQuery } = useValues(nodeDetailSceneLogic({ id }))
    const { updateNodeDescription } = useActions(nodeDetailSceneLogic({ id }))

    const canEdit = userHasAccess(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor,
        savedQuery?.user_access_level
    )

    return (
        <SceneTitleSection
            name={node?.name}
            description={node?.description}
            resourceType={{ type: 'sql_editor' }}
            canEdit={canEdit}
            onDescriptionChange={canEdit ? (description) => updateNodeDescription(description) : undefined}
            isLoading={nodeLoading && !node}
            renameDebounceMs={500}
            saveOnBlur
        />
    )
}
