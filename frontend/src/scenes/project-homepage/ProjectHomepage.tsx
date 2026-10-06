import './ProjectHomepage.scss'

import { useValues } from 'kea'
import { Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { SceneExport } from 'scenes/sceneTypes'

const AiFirstHomepage = lazyWithRetry(() =>
    import('./ai-first/AiFirstHomepage').then((m) => ({ default: m.AiFirstHomepage }))
)
const TodayHome = lazyWithRetry(() => import('./today/TodayHome').then((m) => ({ default: m.TodayHome })))

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

export function ProjectHomepage(): JSX.Element {
    const { todayHomeEnabled } = useValues(projectHomepageLogic)
    return (
        <div className="flex-1 min-h-0">
            <Suspense fallback={<Spinner className="text-3xl mx-auto my-8" />}>
                {todayHomeEnabled ? <TodayHome /> : <AiFirstHomepage />}
            </Suspense>
        </div>
    )
}
