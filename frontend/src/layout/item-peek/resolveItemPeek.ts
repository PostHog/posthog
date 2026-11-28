import { combineUrl } from 'kea-router'
import UrlPattern from 'url-pattern'

import { pathFromWindowToRoutes, urlPatternOptions } from 'lib/utils/kea-router'
import { redirects, routes } from 'scenes/scenes'
import { SceneParams } from 'scenes/sceneTypes'

import { ITEM_PEEK_SCENES } from './itemPeekScenes'

export interface ItemPeekTarget {
    href: string
    path: string
    sceneId: string
    sceneParams: SceneParams
}

/** `/insights/:shortId/edit` and `/dashboard/:id/sharing` name a task on the item, not the item, so they navigate. */
function namesTaskOnItem(pattern: string): boolean {
    const segments = pattern.split('/').filter(Boolean)
    const firstParam = segments.findIndex((segment) => segment.startsWith(':') || segment === '*')
    return (
        firstParam !== -1 && segments.slice(firstParam).some((segment) => !segment.startsWith(':') && segment !== '*')
    )
}

function matchRoute(pattern: string, path: string): Record<string, string> | null {
    const staticPrefix = pattern.split(/[:*(]/)[0]
    if (!path.startsWith(staticPrefix)) {
        return null
    }
    return new UrlPattern(pattern, urlPatternOptions).match(path)
}

export function resolveItemPeek(href: string): ItemPeekTarget | null {
    let path: string
    let searchParams: Record<string, any>
    let hashParams: Record<string, any>
    try {
        const url = combineUrl(href)
        path = pathFromWindowToRoutes(url.pathname)
        searchParams = url.searchParams
        hashParams = url.hashParams
    } catch {
        return null
    }

    // A redirected path lands on another scene, so the drawer could show the wrong page.
    if (Object.keys(redirects).some((pattern) => matchRoute(pattern, path))) {
        return null
    }

    // The first matching route wins, as in sceneLogic.
    for (const [pattern, [sceneId]] of Object.entries(routes)) {
        const params = matchRoute(pattern, path)
        if (!params) {
            continue
        }
        const config = ITEM_PEEK_SCENES[sceneId]
        if (!config || Object.values(params).includes('new') || (namesTaskOnItem(pattern) && !config.nestedRoutes)) {
            return null
        }
        return { href, path, sceneId, sceneParams: { params, searchParams, hashParams } }
    }
    return null
}
