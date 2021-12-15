import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'

export const scene: SceneExport = {
    component: ToolbarLaunch,
    //logic: toolbarLaunchLogic,
}

function ToolbarLaunch(): JSX.Element {
    return (
        <div className="toolbar-launch-page">
            <PageHeader title="Toolbar" />
        </div>
    )
}
