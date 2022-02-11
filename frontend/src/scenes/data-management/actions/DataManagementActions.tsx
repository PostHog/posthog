import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { dataManagementPageLogic } from 'scenes/data-management/dataManagementPageLogic'
import { DataManagementHeader } from 'scenes/data-management/DataManagementHeader'

export function DataManagementActions(): JSX.Element {
    return (
        <>
            <DataManagementHeader />
        </>
    )
}

export const scene: SceneExport = {
    component: DataManagementActions,
    logic: dataManagementPageLogic,
}
