import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { dataManagementPageLogic } from 'scenes/data-management/dataManagementPageLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function ActionWrite(): JSX.Element {
    return (
        <>
            <PageHeader title="Action Edit" />
        </>
    )
}

export const scene: SceneExport = {
    component: ActionWrite,
    logic: dataManagementPageLogic,
}
