import { getResponse, http, type HttpHandler } from 'msw'

type RouteEntry = { handler: HttpHandler; method: string | RegExp; segments: string[] | null }

// Null means the path is too complex to pre-filter, so msw always checks it.
const pathSegments = (path: unknown): string[] | null => {
    if (typeof path !== 'string' || !path.startsWith('/') || /[*?+()\\]/.test(path)) {
        return null
    }
    const segments = path.replace(/\/$/, '').toLowerCase().split('/')
    return segments.some((segment) => segment.includes(':', 1)) ? null : segments
}

// Must never reject a handler msw would accept. msw ignores case and a trailing slash.
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

// Answers like `handlers` in order, but msw only parses the handlers whose method and path can match.
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
