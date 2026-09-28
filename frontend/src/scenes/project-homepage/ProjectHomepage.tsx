import './ProjectHomepage.scss'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { AiFirstHomepage } from './ai-first/AiFirstHomepage'
import { TodayHome } from './today/TodayHome'

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

export function ProjectHomepage(): JSX.Element {
    const todayEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return <div className="flex-1 min-h-0">{todayEnabled ? <TodayHome /> : <AiFirstHomepage />}</div>
}
