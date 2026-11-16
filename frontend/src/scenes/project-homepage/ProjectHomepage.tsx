import './ProjectHomepage.scss'

import { useValues } from 'kea'
import { Suspense } from 'react'

import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { projectHomepageLogic } from 'scenes/project-homepage/projectHomepageLogic'
import { SceneContentFallback } from 'scenes/SceneContentFallback'
import { SceneExport } from 'scenes/sceneTypes'

import { importAiFirstHomepage, importTodayHome } from './importProjectHomepage'

const AiFirstHomepage = lazyWithRetry(() => importAiFirstHomepage().then((m) => ({ default: m.AiFirstHomepage })))
const TodayHome = lazyWithRetry(() => importTodayHome().then((m) => ({ default: m.TodayHome })))

export const scene: SceneExport = {
    component: ProjectHomepage,
    logic: projectHomepageLogic,
}

export function ProjectHomepage(): JSX.Element {
    const { todayHomeEnabled } = useValues(projectHomepageLogic)
    return (
        <div className="flex-1 min-h-0">
            <Suspense
                fallback={
                    <SceneContentFallback>
                        <SpinnerOverlay sceneLevel />
                    </SceneContentFallback>
                }
            >
                {todayHomeEnabled ? <TodayHome /> : <AiFirstHomepage />}
            </Suspense>
        </div>
    )
}
