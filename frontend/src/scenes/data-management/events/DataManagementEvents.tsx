import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { dataManagementPageLogic } from 'scenes/data-management/dataManagementPageLogic'
import { DataManagementHeader } from 'scenes/data-management/DataManagementHeader'

export function DataManagementEvents(): JSX.Element {
    return (
        <>
            <DataManagementHeader />
        </>
    )
}

export const scene: SceneExport = {
    component: DataManagementEvents,
    logic: dataManagementPageLogic,
}
