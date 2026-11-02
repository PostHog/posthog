import UrlPattern from 'url-pattern'

import { pathFromWindowToRoutes, urlPatternOptions } from 'lib/utils/kea-router'
import { appScenes } from 'scenes/appScenes'
import { redirects, routes } from 'scenes/scenes'

function matchesRoute(pattern: string, path: string): boolean {
    // Like kea-router, compare the part before the first param first, because building a pattern is slow.
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

/** Starts to load the code of the scene for this page, so it downloads while the app renders. */
export function prefetchScene(): void {
    const scene = sceneForPathname(window.location.pathname)
    const importScene = scene ? appScenes[scene] : undefined
    // sceneLogic imports the same module again and reports a failure itself.
    importScene?.().catch(() => {})
}
