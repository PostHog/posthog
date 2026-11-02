import posthog from 'posthog-js'
import UrlPattern from 'url-pattern'

import { markBootPhase } from 'lib/utils/bootTiming'
import { pathFromWindowToRoutes, urlPatternOptions } from 'lib/utils/kea-router'
import { appScenes } from 'scenes/appScenes'
import { redirects, routes } from 'scenes/scenes'

function matchesRoute(pattern: string, path: string): boolean {
    const staticPrefix = pattern.split(/[:*(]/)[0]
    return path.startsWith(staticPrefix) && new UrlPattern(pattern, urlPatternOptions).match(path) !== null
}

/** The scene that sceneLogic opens for `pathname`, or null when a redirect handles it or no route matches. */
export function sceneForPathname(pathname: string): string | null {
    let path: string
    try {
        path = pathFromWindowToRoutes(decodeURI(pathname))
    } catch {
        return null
    }
    if (path === '/' || Object.keys(redirects).some((pattern) => matchesRoute(pattern, path))) {
        return null
    }
    const route = Object.entries(routes).find(([pattern]) => matchesRoute(pattern, path))
    return route ? route[1][0] : null
}

/**
 * Starts to load the code of the scene for this page, so it downloads while the app renders.
 * The boot timing event reports the scene, so a wrong guess shows up as a `prefetched_scene` that differs from `scene`.
 */
export function prefetchScene(): void {
    try {
        const scene = sceneForPathname(window.location.pathname)
        const importScene = scene ? appScenes[scene] : undefined
        if (!scene || !importScene) {
            return
        }
        Promise.resolve(importScene()).catch(() => {})
        markBootPhase('scene_prefetched', { prefetched_scene: scene })
    } catch (error) {
        posthog.captureException(error, { extra: { source: 'prefetchScene' } })
    }
}
