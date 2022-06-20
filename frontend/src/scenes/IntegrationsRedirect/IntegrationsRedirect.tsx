import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { integrationsLogic } from 'scenes/project/Settings/integrationsLogic'

export const scene: SceneExport = {
    component: IntegrationsRedirect,
    logic: integrationsLogic,
}

export function IntegrationsRedirect(): JSX.Element {
    return (
        <div className="text-center gap flex">
            <Spinner />
        </div>
    )
}

export default IntegrationsRedirect
