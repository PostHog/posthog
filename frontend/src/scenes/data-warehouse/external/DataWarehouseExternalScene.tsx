import { SceneExport } from 'scenes/sceneTypes'

import { DataWarehouseInitialBillingLimitNotice } from '../DataWarehouseInitialBillingLimitNotice'
import { EditorScene } from '../editor/EditorScene'
import { dataWarehouseExternalSceneLogic } from './dataWarehouseExternalSceneLogic'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseExternalSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    return (
        <>
            <DataWarehouseInitialBillingLimitNotice />
            <EditorScene />
        </>
    )
}
