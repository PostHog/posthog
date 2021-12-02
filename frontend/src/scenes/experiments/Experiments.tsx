import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from './experimentsLogic'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    return (
        <div>
            <PageHeader title="Experiments" caption="Experiments" />
        </div>
    )
}
