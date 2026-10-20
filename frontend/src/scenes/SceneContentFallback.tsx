import { createContext, useContext, useLayoutEffect } from 'react'

import type { SceneRenderedMark } from 'lib/utils/bootTiming'

export const SceneRenderedMarkContext = createContext<SceneRenderedMark | null>(null)

/**
 * Use as the fallback of a scene's own Suspense boundary around its main lazy content, so the
 * `scene_rendered` boot mark waits for that content and not for the fallback.
 */
export function SceneContentFallback({ children }: { children: JSX.Element }): JSX.Element {
    const sceneRendered = useContext(SceneRenderedMarkContext)
    // The release runs as the cleanup, in the commit that replaces this fallback with the content.
    useLayoutEffect(() => sceneRendered?.holdUntilContent(), [sceneRendered])
    return children
}
