import React from 'react'
import { CreateProjectModal } from '../CreateProjectModal'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: ProjectCreate,
}

export function ProjectCreate(): JSX.Element {
    return <CreateProjectModal isVisible />
}
