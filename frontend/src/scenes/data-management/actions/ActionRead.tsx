import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { dataManagementPageLogic } from 'scenes/data-management/dataManagementPageLogic'
import { PageHeader } from 'lib/components/PageHeader'

export function ActionRead(): JSX.Element {
    return (
        <>
            <PageHeader title="Action Read" />
        </>
    )
}

export const scene: SceneExport = {
    component: ActionRead,
    logic: dataManagementPageLogic,
}
