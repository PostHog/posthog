import posthog from 'posthog-js'
import UrlPattern from 'url-pattern'

import { FEATURE_FLAGS } from 'lib/constants'
import { markBootPhase } from 'lib/utils/bootTiming'
import { pathFromWindowToRoutes, urlPatternOptions } from 'lib/utils/kea-router'
import { appScenes } from 'scenes/appScenes'
import { getBootstrappedHomepage, homepageTargetPathname } from 'scenes/sceneLogic'
import { redirects, routes } from 'scenes/scenes'
import { urls } from 'scenes/urls'

function matchesRoute(pattern: string, path: string): boolean {
    const staticPrefix = pattern.split(/[:*(]/)[0]
    return path.startsWith(staticPrefix) && new UrlPattern(pattern, urlPatternOptions).match(path) !== null
}

function routePath(target: string): string {
    return pathFromWindowToRoutes(target.split(/[?#]/)[0])
}

/** Follows at most one redirect or homepage hop, so a redirect loop cannot recurse. */
function sceneForRoutePath(path: string, followRedirects: boolean): string | null {
    // sceneLogic sends `/` to the homepage, so the root resolves the same way as `/home`.
    const homePath = urls.projectHomepage()
    const matchPath = path === '/' ? homePath : path
    const redirect = Object.entries(redirects).find(([pattern]) => matchesRoute(pattern, matchPath))
    if (redirect) {
        const [, target] = redirect
        // A function target builds its path from the request's params and query, which the boot does not resolve.
        return followRedirects && typeof target === 'string' ? sceneForRoutePath(routePath(target), false) : null
    }
    // sceneLogic ignores a saved homepage when the rail navigation is on, and opens the project homepage instead.
    const followsSavedHomepage =
        followRedirects &&
        matchPath === homePath &&
        !posthog.isFeatureEnabled(FEATURE_FLAGS.TODAY_RAIL_NAV, { send_event: false })
    const homepage = followsSavedHomepage ? getBootstrappedHomepage() : null
    if (homepage) {
        return sceneForRoutePath(routePath(homepageTargetPathname(homepage)), false)
    }
    const route = Object.entries(routes).find(([pattern]) => matchesRoute(pattern, matchPath))
    return route ? route[1][0] : null
}

/** The scene that sceneLogic opens for `pathname`, or null when it cannot be known before the router runs. */
export function sceneForPathname(pathname: string): string | null {
    let path: string
    try {
        path = pathFromWindowToRoutes(decodeURI(pathname))
    } catch {
        return null
    }
    return sceneForRoutePath(path, true)
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
