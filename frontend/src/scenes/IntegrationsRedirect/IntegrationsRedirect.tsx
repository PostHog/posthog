import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { slackIntegrationLogic } from 'scenes/project/Settings/slackIntegrationLogic'

export const scene: SceneExport = {
    component: IntegrationsRedirect,
    logic: slackIntegrationLogic,
}

export function IntegrationsRedirect(): JSX.Element {
    return (
        <div className="text-center gap flex">
            <Spinner />
        </div>
    )
}

export default IntegrationsRedirect
