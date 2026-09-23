import './ProjectHomepage.scss'

import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { AiFirstHomepage } from './ai-first/AiFirstHomepage'

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

export function ProjectHomepage(): JSX.Element {
    return (
        <div className="flex-1 min-h-0">
            <AiFirstHomepage />
        </div>
    )
}
