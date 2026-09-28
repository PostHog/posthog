import { getPluginContext } from 'kea'
import { combineUrl, decodeParams, router } from 'kea-router'

import type { EmbedHost, EmbedLocation } from './embedTypes'

interface EmbedRouterBinding {
    /** Passed to kea-router as `history`. It calls only pushState and replaceState. */
    history: Pick<History, 'pushState' | 'replaceState'>
    /** Passed to kea-router as `location`. kea-router reads it again on every popstate event. */
    location: EmbedLocation
}

/** Points kea-router at the host's URL instead of `window.location`, so the app and the host share one history. */
export function createEmbedRouterBinding(host: EmbedHost): EmbedRouterBinding {
    return {
        history: {
            pushState: (_state, _title, url) => host.navigate(String(url), { replace: false }),
            replaceState: (_state, _title, url) => host.navigate(String(url), { replace: true }),
        },
        location: {
            get pathname() {
                return host.getLocation().pathname
            },
            get search() {
                return host.getLocation().search
            },
            get hash() {
                return host.getLocation().hash
            },
        },
    }
}

/**
 * Tells kea-router about a location change the host made itself, for example from a link in the host's
 * own navigation. The change arrives as a POP, the same way a back or forward step does. A location the
 * app already shows is skipped, because the app's own navigations come back through the host as well.
 */
export function syncRouterFromHost(host: EmbedHost): void {
    const { pathname: hostPathname, search, hash } = host.getLocation()
    const transformPath = (getPluginContext('router') as { transformPathInActions?: (path: string) => string })
        .transformPathInActions
    const pathname = transformPath ? transformPath(hostPathname) : hostPathname
    const url = combineUrl(pathname, search, hash).url
    const current = router.values.currentLocation
    if (url === combineUrl(current.pathname, current.search, current.hash).url) {
        return
    }
    router.actions.locationChanged({
        method: 'POP',
        pathname,
        search,
        searchParams: decodeParams(search, '?'),
        hash,
        hashParams: decodeParams(hash, '#'),
        url,
    })
}
