import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { tryDecodeURIComponent } from 'lib/utils/url'
import { urls } from 'scenes/urls'

const SESSION_PAGE_PATH = new RegExp(`^${urls.aiObservabilitySessions()}/([^/]+)/?$`)

function tryDecodeURI(value: string): string {
    try {
        return decodeURI(value)
    } catch {
        return value
    }
}

/**
 * The session a session page path opens, or null on any other path. The path is read as the browser holds it, so both
 * layers that `urls.aiObservabilitySession` encodes come off: the one the router takes off before matching, then the
 * one it keeps.
 */
export function sessionPageIdFromPath(pathname: string): string | null {
    const segment = SESSION_PAGE_PATH.exec(removeProjectIdIfPresent(pathname))?.[1]
    return segment ? tryDecodeURIComponent(tryDecodeURI(segment)) : null
}
