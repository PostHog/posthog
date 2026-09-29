import './ProjectHomepage.scss'

import { useValues } from 'kea'

import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { AiFirstHomepage } from './ai-first/AiFirstHomepage'
import { TodayHome } from './today/TodayHome'

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

export function ProjectHomepage(): JSX.Element {
    const { todayHomeEnabled } = useValues(projectHomepageLogic)
    return <div className="flex-1 min-h-0">{todayHomeEnabled ? <TodayHome /> : <AiFirstHomepage />}</div>
}
