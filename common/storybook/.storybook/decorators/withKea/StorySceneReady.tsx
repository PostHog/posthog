import { ReactNode, useLayoutEffect, useState } from 'react'

import { createSceneRenderedMark } from 'lib/utils/bootTiming'
import { SceneRenderedMarkContext } from 'scenes/SceneContentFallback'

let nextInstanceId = 0

export function StorySceneReady({ storyId, children }: { storyId: string; children: ReactNode }): JSX.Element {
    const [instanceId] = useState(() => ++nextInstanceId)
    const [sceneRendered] = useState(() =>
        createSceneRenderedMark(() => performance.mark?.('posthog:storybook:scene_rendered'))
    )
    useLayoutEffect(() => {
        performance.clearMarks?.('posthog:storybook:scene_rendered')
        const readiness = { storyId, instanceId, getReadyVersion: sceneRendered.getReadyVersion }
        window.__STORYBOOK_SCENE_READINESS__ = readiness
        sceneRendered.sceneCommitted()
        return () => {
            sceneRendered.sceneUncommitted()
            if (window.__STORYBOOK_SCENE_READINESS__ === readiness) {
                delete window.__STORYBOOK_SCENE_READINESS__
            }
        }
    }, [sceneRendered, storyId, instanceId])
    return <SceneRenderedMarkContext.Provider value={sceneRendered}>{children}</SceneRenderedMarkContext.Provider>
}
