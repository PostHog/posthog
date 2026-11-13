import { useValues } from 'kea'
import { Suspense } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'
import { sceneLogic } from 'scenes/sceneLogic'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneConfig } from 'scenes/sceneTypes'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import type { ProjectNotice as ProjectNoticeComponent } from '../../navigation/ProjectNotice'

// The notice logic pulls in dompurify, the sample data logic and the product push branding.
const loadProjectNotice = (): Promise<{ default: typeof ProjectNoticeComponent }> =>
    import('../../navigation/ProjectNotice').then(({ ProjectNotice }) => ({ default: ProjectNotice }))
// Start the fetch at boot, so the banner usually lands before the scene paints and does not push it down.
void loadProjectNotice().catch(() => {})
const ProjectNotice = lazyWithRetry(loadProjectNotice)

/** sceneConfig follows the routed scene, so an error scene that replaces it (activeSceneId) needs its own lookup. */
export function sceneHidesProjectNotice(sceneConfig: SceneConfig | null, activeSceneId: string | null): boolean {
    return !!(
        sceneConfig?.hideProjectNotice ||
        (activeSceneId && sceneConfigurations[activeSceneId]?.hideProjectNotice)
    )
}

/** SceneMenuBar replaces the project notice, so hide the notice when the menu bar is on. */
export function ProjectNoticeSlot({
    sceneConfig,
    noPaddingScene,
}: {
    sceneConfig: SceneConfig | null
    noPaddingScene: boolean
}): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { activeSceneId } = useValues(sceneLogic)

    if (sceneMenuBarEnabled || sceneHidesProjectNotice(sceneConfig, activeSceneId)) {
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
                <ChunkLoadErrorBoundary>
                    <Suspense fallback={null}>
                        <ProjectNotice
                            hiddenVariants={
                                todayRailNav && activeSceneId === Scene.ProjectHomepage
                                    ? ['real_project_with_no_events']
                                    : undefined
                            }
                            className={cn('my-0 mb-4', {
                                'mt-4': noPaddingScene,
                            })}
                        />
                    </Suspense>
                </ChunkLoadErrorBoundary>
            </ErrorBoundary>
        </div>
    )
}
