import { useValues } from 'kea'
import { ViewLinkModal } from 'scenes/data-warehouse/ViewLinkModal'
import { SceneExport } from 'scenes/sceneTypes'

import { dataModelSceneLogic } from './dataModelSceneLogic'
import NodeCanvasWithTable from './NodeCanvasWithTable'

export const scene: SceneExport = {
    component: DataModelScene,
    logic: dataModelSceneLogic,
}

export function DataModelScene(): JSX.Element {
    const { simplifiedPersonFields, joinedFieldsAsNodes, allNodes } = useValues(dataModelSceneLogic)

    return (
        <>
            <NodeCanvasWithTable
                nodes={allNodes}
                fixedFields={simplifiedPersonFields}
                joinedFields={joinedFieldsAsNodes}
                tableName="persons"
            />
            <ViewLinkModal />
        </>
    )
}
