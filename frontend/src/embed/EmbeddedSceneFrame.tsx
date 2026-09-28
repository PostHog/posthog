import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'
import { ActiveScene } from 'scenes/ActiveScene'
import { sceneLogic } from 'scenes/sceneLogic'

import { SceneLayout } from '~/layout/scenes/SceneLayout'

/**
 * The main content column of the full app layout (layout/navigation-3000/Navigation.tsx), without the
 * left navigation and the side panel. Scenes break on the `main-content` container queries, so the
 * container names and the `#main-content` id are kept.
 */
export function EmbeddedSceneFrame(): JSX.Element {
    const { sceneConfig } = useValues(sceneLogic)
    const noPaddingScene = sceneConfig?.layout === 'app-raw-no-header' || sceneConfig?.layout === 'app-raw'

    return (
        <div className="@container/main-content-container main-content-container flex h-full overflow-hidden relative">
            <main
                id="main-content"
                className={cn(
                    '@container/main-content bg-[var(--scene-layout-background)] overflow-y-auto overflow-x-hidden show-scrollbar-on-hover p-4 pb-0 h-full flex-1 flex flex-col',
                    { 'p-0': noPaddingScene }
                )}
            >
                <SceneLayout sceneConfig={sceneConfig}>
                    <ActiveScene />
                </SceneLayout>
            </main>
        </div>
    )
}
