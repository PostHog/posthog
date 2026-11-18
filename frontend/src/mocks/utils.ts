import { http, HttpResponse, type DefaultBodyType, type HttpHandler, type HttpResponseResolver } from 'msw'

export const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options'] as const
export type HttpMethod = (typeof HTTP_METHODS)[number]

// The resolver argument MSW v2 passes to a handler: `{ request, params, cookies, requestId }`.
export type MockResolverInfo = Parameters<HttpResponseResolver>[0]

// What a mock resolves to:
// 1. A `[status, body]` tuple
// 2. A `[status]` tuple
// 3. `undefined`/`null` — an empty 200 (matches v1's `res()`); for a real network error
//    return `HttpResponse.error()` explicitly
// 4. A `Response`/`HttpResponse`
// 5. Any other value — returned as a JSON body
type MockResult = Response | [number, DefaultBodyType?] | DefaultBodyType | null | undefined

export type MockSignature = ((info: MockResolverInfo) => MockResult | Promise<MockResult>) | Record<string, any> | any[]
export type Mocks = Partial<Record<HttpMethod, Record<string, MockSignature>>>

const toResponse = (result: MockResult): Response => {
    if (result instanceof Response) {
        return result
    }
    if (Array.isArray(result)) {
        if (result.length === 2 && typeof result[0] === 'number') {
            return HttpResponse.json(result[1] ?? null, { status: result[0] })
        }
        if (result.length === 1 && typeof result[0] === 'number') {
            return new HttpResponse(null, { status: result[0] })
        }
        // Any other array is a JSON array body.
        return HttpResponse.json(result)
    }
    if (result == null) {
        // A bare empty return is an empty 200, matching v1's `res()`. This is the fall-through
        // for handlers with conditional branches and no final else (e.g. a query mock that only
        // covers some kinds) — it must NOT be a network error, or apiStatusLogic flips the whole
        // app into the "trouble connecting to the server" banner. Return HttpResponse.error()
        // explicitly to model a real network failure.
        return new HttpResponse(null, { status: 200 })
    }
    return HttpResponse.json(result)
}

const ENVIRONMENTS_PATH = /(^|\/)api\/environments\//

const withoutTrailingSlash = (path: string): string => path.replace(/\/$/, '')

// The key two registrations share when MSW matches them against the same requests. A `:param`
// segment matches any single segment, so its name carries no meaning, and a trailing slash is
// stripped before a handler is registered.
const matchKey = (path: string): string =>
    withoutTrailingSlash(path)
        .split('/')
        .map((segment) => (segment.startsWith(':') ? ':param' : segment))
        .join('/')

// `/api/environments/` is a deprecated alias of `/api/projects/`: EnvironmentsRewriteMiddleware
// rewrites it in-process to the same viewset, so a mock registered on one path must answer the
// other. Serving the twin here keeps the existing environments registrations working while the
// frontend moves to the canonical projects path.
// The alias is one-way on purpose. A projects registration never answers an environments request,
// so a hand-written environments URL left in source still fails its test.
const projectsTwinFor = (path: string, registeredPaths: Set<string>): string | null => {
    if (!ENVIRONMENTS_PATH.test(path)) {
        return null
    }
    const twin = path.replace(ENVIRONMENTS_PATH, '$1api/projects/')
    // The same route registered on both paths needs no twin.
    return registeredPaths.has(matchKey(twin)) ? null : twin
}

// True when `pattern` matches every request `other` matches and more, because it has a `:param`
// segment where `other` names a literal. MSW answers with the first match, so a looser pattern
// registered earlier hides the stricter one.
const covers = (pattern: string, other: string): boolean => {
    const loose = matchKey(pattern).split('/')
    const strict = matchKey(other).split('/')
    if (loose.length !== strict.length) {
        return false
    }
    let looserSomewhere = false
    for (let i = 0; i < loose.length; i++) {
        if (loose[i] === strict[i]) {
            continue
        }
        if (loose[i] !== ':param') {
            return false
        }
        looserSomewhere = true
    }
    return looserSomewhere
}

export const mocksToHandlers = (mocks: Mocks): HttpHandler[] => {
    const handlers: HttpHandler[] = []
    // A twin that would hide a projects route the map registers on purpose goes last instead of in
    // place. Only those move, because registration order decides which handler MSW picks and tests
    // depend on the order their mocks resolve in.
    const deferred: HttpHandler[] = []
    Object.entries(mocks)
        .filter((entry): entry is [HttpMethod, Record<string, MockSignature>] => !!entry[1])
        .forEach(([method, mockHandlers]) => {
            const paths = Object.keys(mockHandlers)
            const registeredPaths = new Set(paths.map(matchKey))
            const projectsPaths = paths.filter((path) => !ENVIRONMENTS_PATH.test(path))
            Object.entries(mockHandlers).forEach(([path, handler]) => {
                // Function handlers and static values support the same MockResult forms: a
                // `[status, body]` tuple, a Response, or a plain JSON body. Static `[status, body]`
                // tuples used to be serialized as a literal array body, which silently broke every
                // mock relying on the status.
                const resolve = async (info: MockResolverInfo): Promise<Response> =>
                    typeof handler === 'function' ? toResponse(await handler(info)) : toResponse(handler as MockResult)

                handlers.push((http[method] as (typeof http)['get'])(withoutTrailingSlash(path), resolve))

                const twin = projectsTwinFor(path, registeredPaths)
                if (twin) {
                    const target = projectsPaths.some((projectsPath) => covers(twin, projectsPath))
                        ? deferred
                        : handlers
                    target.push((http[method] as (typeof http)['get'])(withoutTrailingSlash(twin), resolve))
                }
            })
        })
    return [...handlers, ...deferred]
}
