import { getResponse, http, type HttpHandler } from 'msw'

type RouteEntry = { handler: HttpHandler; method: string | RegExp; segments: string[] | null }

// The literal segments of a relative path such as `/api/projects/:team_id/cohorts`, lowercased.
// Returns null for any path that the segment check can not decide, so that msw always matches it.
const pathSegments = (path: unknown): string[] | null => {
    if (typeof path !== 'string' || !path.startsWith('/') || /[*?+()\\]/.test(path)) {
        return null
    }
    const segments = path.replace(/\/$/, '').toLowerCase().split('/')
    return segments.some((segment) => segment.includes(':', 1)) ? null : segments
}

// A necessary condition for a match by msw, which matches paths without case and with an optional
// trailing slash. It may accept a handler that msw then rejects, but it never rejects a handler that
// msw would accept.
const mayMatch = (entry: RouteEntry, method: string, requestSegments: string[]): boolean => {
    const methodMatches =
        typeof entry.method === 'string' ? entry.method.toUpperCase() === method : entry.method.test(method)
    if (!methodMatches) {
        return false
    }
    if (!entry.segments) {
        return true
    }
    return (
        entry.segments.length === requestSegments.length &&
        entry.segments.every((segment, i) =>
            segment.startsWith(':') ? requestSegments[i] !== '' : segment === requestSegments[i]
        )
    )
}

/**
 * One handler that answers like `handlers` would, in the same order. msw parses a request again for
 * every handler it checks, and the default mocks have hundreds. This handler filters them by method and
 * path segments with string compares, and lets msw run only the remaining ones. When none of them
 * answers, it answers nothing, so msw reports the request as unhandled.
 */
export const routeHandlers = (handlers: HttpHandler[]): HttpHandler => {
    const entries: RouteEntry[] = handlers.map((handler) => ({
        handler,
        method: handler.info.method,
        segments: pathSegments(handler.info.path),
    }))
    return http.all('*', ({ request }) => {
        const requestSegments = new URL(request.url).pathname.replace(/\/$/, '').toLowerCase().split('/')
        const method = request.method.toUpperCase()
        const candidates = entries.filter((entry) => mayMatch(entry, method, requestSegments))
        return candidates.length > 0
            ? getResponse(
                  candidates.map((entry) => entry.handler),
                  request
              )
            : undefined
    })
}
