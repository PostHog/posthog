import { combineUrl } from 'kea-router'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'

/**
 * The `router.actions.locationChanged` payload of a page load on `url`, for tests. A page load reads the URL as typed,
 * where `router.actions.push` would write a typed `1.50` back as `1.5` before any logic read it.
 */
export function pageLoad(url: string): {
    method: 'POP'
    pathname: string
    search: string
    searchParams: Record<string, unknown>
    hash: string
    hashParams: Record<string, unknown>
    url: string
} {
    const windowUrl = addProjectIdIfMissing(url)
    const { pathname, search, hash } = new URL(windowUrl, 'https://example.com')
    const { searchParams, hashParams } = combineUrl(windowUrl)
    return { method: 'POP', pathname, search, searchParams, hash, hashParams, url: windowUrl }
}
