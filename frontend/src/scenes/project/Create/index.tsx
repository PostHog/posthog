import React, { useState } from 'react'
import { CreateProjectModal } from '../CreateProjectModal'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: ProjectCreate,
}

export function ProjectCreate(): JSX.Element {
    const [isVisible, setIsVisible] = useState(true)

    return <CreateProjectModal isVisible={isVisible} onClose={() => setIsVisible(false)} />
}
