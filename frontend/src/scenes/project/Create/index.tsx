import React from 'react'
import { CreateProjectModal } from '../CreateProjectModal'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: Create,
}

export function Create(): JSX.Element {
    return <CreateProjectModal isVisible />
}
