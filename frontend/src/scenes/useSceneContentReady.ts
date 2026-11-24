import { useContext, useLayoutEffect } from 'react'

import { SceneRenderedMarkContext } from './SceneContentFallback'

/** Keep ready false from the first render until all snapshot-visible work, including debounces, has completed. */
export function useSceneContentReady(ready: boolean): void {
    const sceneRendered = useContext(SceneRenderedMarkContext)
    useLayoutEffect(() => {
        if (!ready) {
            return sceneRendered?.holdUntilContent()
        }
    }, [ready, sceneRendered])
}
