import { useValues } from 'kea'
import { Suspense } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene, SceneConfig } from 'scenes/sceneTypes'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

// The notice logic pulls in dompurify, the sample data logic and the product push branding.
const ProjectNotice = lazyWithRetry(() =>
    import('../../navigation/ProjectNotice').then(({ ProjectNotice }) => ({ default: ProjectNotice }))
)

/** SceneMenuBar replaces the project notice, so hide the notice when the menu bar is on. */
export function ProjectNoticeSlot({
    sceneConfig,
    noPaddingScene,
}: {
    sceneConfig: SceneConfig | null
    noPaddingScene: boolean
}): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const { activeSceneId } = useValues(sceneLogic)

    if (sceneMenuBarEnabled || sceneConfig?.hideProjectNotice) {
        return null
    }

    return (
        <div
            className={cn({
                'px-4 empty:hidden': sceneConfig?.layout === 'app-raw-no-header',
                // Clear the viewport-fixed settings nav so the banner aligns with the content column.
                'md:ml-[calc(var(--settings-nav-width)+2rem)]': activeSceneId === Scene.Settings,
            })}
        >
            <ErrorBoundary>
                <Suspense fallback={null}>
                    <ProjectNotice
                        className={cn('my-0 mb-4', {
                            'mt-4': noPaddingScene,
                        })}
                    />
                </Suspense>
            </ErrorBoundary>
        </div>
    )
}
