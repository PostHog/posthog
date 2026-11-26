import { urls } from 'scenes/urls'

import { aiObservabilitySessionsPreviewsCreateBodySessionIdsItemMax } from '../../generated/api.zod'
import { shellHref } from '../shell/shellNavigation'

// A browser resolves a `.` or `..` path segment away before the app reads the path, and no read takes a longer id.
function fitsPath(sessionId: string): boolean {
    return (
        sessionId !== '.' &&
        sessionId !== '..' &&
        sessionId.length <= aiObservabilitySessionsPreviewsCreateBodySessionIdsItemMax
    )
}

/**
 * The link to a session's own page, or null for an id a path cannot carry. Such a session still opens beside the list,
 * where its id travels as a query param.
 */
export function sessionPageHref(
    sessionId: string,
    timestamp: string | null,
    linkParams: Record<string, unknown>
): string | null {
    if (!fitsPath(sessionId)) {
        return null
    }
    return shellHref(urls.aiObservabilitySession(sessionId, timestamp ? { timestamp } : undefined), linkParams)
}
