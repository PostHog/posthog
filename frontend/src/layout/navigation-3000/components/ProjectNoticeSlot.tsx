import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene, SceneConfig } from 'scenes/sceneTypes'

import { ProjectNotice } from '../../navigation/ProjectNotice'

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
            <ProjectNotice
                className={cn('my-0 mb-4', {
                    'mt-4': noPaddingScene,
                })}
            />
        </div>
    )
}
